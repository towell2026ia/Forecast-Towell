"""FastAPI read service for PRD 08B. Bind to 127.0.0.1 in local mode."""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .data_provider import DataProvider, NormalizedDataProvider
from .historical_runner import HistoricalForecastRunner
from .orchestrator import ForecastOrchestrator

API_VERSION = "prd08c1-1.0.0"


class AssistantMessage(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    context: dict[str, Any] = Field(default_factory=dict)


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").casefold() == "true"


def _authorized_actor(request: Request, x_assistant_token: str | None = Header(default=None),
                      x_actor_id: str | None = Header(default=None)) -> str:
    """Verify server-issued identity; a browser-supplied role has no authority."""
    configured_token = os.getenv("ASSISTANT_API_TOKEN")
    managers = {item.strip() for item in os.getenv("ASSISTANT_MANAGER_IDS", "").split(",") if item.strip()}
    local = _flag("ASSISTANT_LOCAL_MODE", True) and request.client is not None and request.client.host in {
        "127.0.0.1", "::1", "testclient"
    }
    if configured_token:
        if not x_assistant_token or not hmac.compare_digest(x_assistant_token, configured_token):
            raise HTTPException(status_code=401, detail="assistant_auth_required")
    elif not local:
        raise HTTPException(status_code=401, detail="assistant_auth_required")
    if local and not managers:
        managers = {"local-manager"}
    if not x_actor_id or x_actor_id not in managers:
        raise HTTPException(status_code=403, detail="assistant_permission_denied")
    return x_actor_id


def create_app(provider: DataProvider | None = None, historical_state_dir: Path | None = None) -> FastAPI:
    data = provider or NormalizedDataProvider()
    app = FastAPI(title="FORECAST Towell Assistant API", version=API_VERSION)
    orchestrator = ForecastOrchestrator(data)
    app.state.orchestrator = orchestrator
    state_dir = historical_state_dir or (getattr(data, "state_dir", None) / "historical"
                                         if getattr(data, "state_dir", None) else None)
    historical = HistoricalForecastRunner(data, state_dir=state_dir)
    app.state.historical = historical

    @app.get("/api/historical/availability/audit")
    def historical_availability_audit(chain: str = "Walmart", start_period: str = "2023-01",
                                      end_period: str = "2026-08",
                                      actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
        _ = actor
        try:
            return historical.availability.audit_availability(start_period, end_period, chain=chain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/api/historical/readiness/{period}")
    def historical_readiness(period: str, chain: str = "Walmart", cutoff: str | None = None,
                             actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
        _ = actor
        try:
            return historical.availability.validate_temporal_readiness(period, chain=chain, cutoff=cutoff)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/api/historical/first-valid-period")
    def historical_first_valid(chain: str = "Walmart", start_period: str = "2023-01",
                               end_period: str = "2026-08",
                               actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
        _ = actor
        try:
            return {"first_valid_period": historical.availability.find_first_temporally_valid_period(
                start_period, end_period, chain=chain)}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.post("/api/historical/first-vintage")
    def historical_first_vintage(actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
        return historical.first_vintage(actor=actor)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            statistical = data.load("statistical")
            ml = data.load("ml")
            ensemble = data.load("ensemble")
            return {"status": "ok", "version": API_VERSION, "python_api": True,
                    "data_provider": data.name,
                    "motors": {"statistical": statistical["run"]["engine_version"],
                               "ml": ml["engine_version"], "ensemble": ensemble["engine_version"]},
                    "cutoff": ensemble["cutoff"],
                    "flags": {"AI_ASSISTANT_UI_ENABLED": _flag("AI_ASSISTANT_UI_ENABLED", True),
                              "AI_ASSISTANT_API_ENABLED": _flag("AI_ASSISTANT_API_ENABLED", True),
                              "OPENAI_ENABLED": False, "DEEP_RESEARCH_ENABLED": False,
                              "VOICE_ENABLED": False, "SUPABASE_ENABLED": False,
                              "LOCAL_INTENT_ROUTER_ENABLED": _flag("LOCAL_INTENT_ROUTER_ENABLED", True),
                              "MONTHLY_RUNNER_ENABLED": _flag("MONTHLY_RUNNER_ENABLED", True)}}
        except Exception:
            return {"status": "degraded", "version": API_VERSION, "python_api": True,
                    "data_provider": data.name, "motors": {}, "cutoff": None}

    @app.post("/api/assistant/message")
    def assistant_message(body: AssistantMessage, actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
        if not _flag("AI_ASSISTANT_API_ENABLED", True) or not _flag("LOCAL_INTENT_ROUTER_ENABLED", True):
            raise HTTPException(status_code=503, detail="assistant_disabled")
        try:
            result = orchestrator.answer(body.message, body.context)
            result["metadata"]["actor"] = actor
            return result
        except Exception:
            raise HTTPException(status_code=503, detail="assistant_data_unavailable") from None

    def read_tool(intent: str, product: str | None, category: str | None, color: str | None,
                  period: str | None, issue_period: str | None, target_period: str | None) -> dict[str, Any]:
        try:
            return orchestrator.query(intent, {"product": product, "category": category, "color": color,
                                                "period": period, "issue_period": issue_period,
                                                "target_period": target_period})
        except Exception:
            raise HTTPException(status_code=503, detail="assistant_data_unavailable") from None

    ROUTES = {
        "/api/forecast/current": "current_forecast",
        "/api/forecast/12m": "forecast_12m",
        "/api/performance/wape": "wape_summary",
        "/api/performance/bias": "bias_summary",
        "/api/performance/fill-rate": "fill_rate",
        "/api/performance/product": "product_performance",
        "/api/performance/highest-error": "highest_error_series",
        "/api/models/champion": "champion_status",
        "/api/models/challenger": "challenger_status",
        "/api/models/drift": "drift_status",
        "/api/forecast/vintages": "forecast_vintage",
        "/api/forecast/bands": "probability_bands",
        "/api/forecast/comparison": "forecast_comparison",
        "/api/decisions/history": "decision_history",
        "/api/decisions/fva": "fva_summary",
        "/api/periods/status": "period_status",
    }

    def make_endpoint(selected_intent: str):
        def endpoint(product: str | None = None, category: str | None = None, color: str | None = None,
                     period: str | None = None, issue_period: str | None = None, target_period: str | None = None,
                     actor: str = Depends(_authorized_actor)) -> dict[str, Any]:
            _ = actor
            return read_tool(selected_intent, product, category, color, period, issue_period, target_period)
        return endpoint

    for path, intent in ROUTES.items():
        app.get(path, name=intent)(make_endpoint(intent))
    return app


app = create_app()
