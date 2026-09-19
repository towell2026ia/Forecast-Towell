"""Operational Supabase adapter for the PRD 04 global ML engine.

Required environment: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ML_TRAINING_RUN_ID.
The adapter reads closed normalized observations from the database, trains outside the
request cycle, persists the evidence, and never promotes over an existing Champion.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from engine import ENGINE_VERSION, Series, build_payload_from_series


class Supabase:
    def __init__(self) -> None:
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    def request(self, method: str, path: str, payload=None, prefer: str | None = None):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.url}/rest/v1/{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Supabase {method} {path}: {error.code} {detail}") from error

    def patch_run(self, run_id: str, **fields) -> None:
        self.request("PATCH", f"ml_training_runs?id=eq.{run_id}", fields, "return=minimal")


def log(db: Supabase, run_id: str, stage: str, status: str, message: str, **details) -> None:
    db.request(
        "POST",
        "ml_training_log",
        {"training_run_id": run_id, "stage": stage, "status": status, "message": message, "details": details},
        "return=minimal",
    )


def main() -> None:
    started = time.perf_counter()
    db, run_id = Supabase(), os.environ["ML_TRAINING_RUN_ID"]
    rows = db.request("GET", f"ml_training_runs?id=eq.{run_id}&select=*&limit=1")
    if not rows:
        raise RuntimeError("ML training run not found")
    run = rows[0]
    target = run["target"]
    value_column = "sale" if target == "Venta" else "orders"
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.patch_run(run_id, status="preparing_data", started_at=now)
        log(db, run_id, "preparing_data", "started", "Leyendo observaciones normalizadas y cerradas")
        query = urllib.parse.urlencode(
            {
                "organization_id": f"eq.{run['organization_id']}",
                "chain_id": f"eq.{run['chain_id']}",
                "select": f"product_id,description,color,category,period_start,{value_column}",
                "order": "period_start.asc",
            }
        )
        observations = db.request("GET", f"ml_training_observations?{query}") or []
        grouped: dict[str, Series] = {}
        fingerprint_rows = []
        for row in observations:
            product_id = row["product_id"]
            series = grouped.setdefault(
                product_id,
                Series(
                    product_id,
                    (row.get("description") or product_id).replace("TOALLA MB FENDI ", "").title(),
                    row.get("color") or "Sin color",
                    row.get("category") or "Sin categoría",
                    {},
                ),
            )
            period = row["period_start"][:7]
            value = row.get(value_column)
            series.points[period] = None if value is None else float(value)
            fingerprint_rows.append((product_id, period, value))
        if not grouped or not any(value is not None for series in grouped.values() for value in series.points.values()):
            raise ValueError(f"No existen observaciones cerradas para {target}")

        db.patch_run(run_id, status="training")
        log(db, run_id, "training", "started", "Entrenando candidatos globales", series=len(grouped))
        payload = build_payload_from_series(list(grouped.values()), target)
        if payload.get("status") == "insufficient":
            raise ValueError(payload.get("reason", "Datos insuficientes"))

        db.patch_run(run_id, status="backtesting")
        log(db, run_id, "backtesting", "completed", "Validación temporal sin fuga completada", horizons=12)
        db.patch_run(run_id, status="evaluating")
        champion = payload["champion"]
        current = db.request(
            "GET",
            "ml_model_versions?"
            + urllib.parse.urlencode(
                {
                    "organization_id": f"eq.{run['organization_id']}",
                    "chain_id": f"eq.{run['chain_id']}",
                    "target": f"eq.{target}",
                    "state": "eq.champion",
                    "select": "id,version_label,wape,bias",
                    "limit": "1",
                }
            ),
        )
        initial_state = "challenger" if current else "evaluating"
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_rows, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        periods = sorted(period for series in grouped.values() for period in series.points)
        version_label = f"ML-FENDI-{target.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{run_id[:8]}"
        version = db.request(
            "POST",
            "ml_model_versions",
            {
                "training_run_id": run_id,
                "organization_id": run["organization_id"],
                "chain_id": run["chain_id"],
                "target": target,
                "version_label": version_label,
                "state": initial_state,
                "algorithm": champion["model"],
                "strategy": "direct",
                "training_start": periods[0] + "-01",
                "training_end": payload["cutoff"] + "-01",
                "feature_schema": {
                    "features": champion["feature_names"],
                    "known": payload["training"]["known_features"],
                    "future_excluded": payload["training"]["unknown_features_excluded"],
                    "nulls_are_zero": False,
                },
                "hyperparameters": {"runtime": "portable_numpy", "candidate_score": champion["score"]},
                "dataset_fingerprint": fingerprint,
                "observation_count": payload["dataset"]["observations"],
                "series_count": payload["dataset"]["series"],
                "training_duration_ms": round((time.perf_counter() - started) * 1000),
                "wape": champion["wape"],
                "bias": champion["bias"],
                "stability": champion["stability"],
                "mae": champion["mae"],
                "rmse": champion["rmse"],
                "created_by": run.get("requested_by"),
            },
            "return=representation",
        )[0]
        version_id = version["id"]

        for metric in champion["by_horizon"]:
            db.request(
                "POST",
                "ml_horizon_metrics",
                {"model_version_id": version_id, **metric},
                "return=minimal",
            )
        for forecast in payload["forecast"]:
            product_id = None if forecast["series_id"] == "total-fendi-bd" else forecast["series_id"]
            source = grouped.get(product_id) if product_id else None
            for point in forecast["forecast"]:
                db.request(
                    "POST",
                    "ml_predictions",
                    {
                        "model_version_id": version_id,
                        "product_id": product_id,
                        "color": source.color if source else None,
                        "category": source.category if source else None,
                        "forecast_date": point["period"] + "-01",
                        "horizon": point["horizon"],
                        "value": point["value"],
                        "historical_wape": champion["wape"],
                        "historical_bias": champion["bias"],
                        "confidence_level": forecast["evidence"],
                    },
                    "return=minimal",
                )
        for feature in payload["feature_importance"]:
            db.request(
                "POST",
                "ml_feature_importance",
                {"model_version_id": version_id, "feature_name": feature["feature"], "importance": feature["importance"] / 100, "method": "native"},
                "return=minimal",
            )
        for alert in payload["alerts"]:
            db.request(
                "POST",
                "ml_alerts",
                {"training_run_id": run_id, "model_version_id": version_id, "alert_type": "data_drift" if alert["type"] == "drift" else "low_evidence", "severity": alert["severity"], "message": alert["message"]},
                "return=minimal",
            )

        if current:
            incumbent = current[0]
            if champion["wape"] < float(incumbent["wape"] or 1e30):
                db.request(
                    "POST",
                    "ml_alerts",
                    {"training_run_id": run_id, "model_version_id": version_id, "alert_type": "challenger_better", "severity": "info", "message": f"El Challenger mejora el WAPE del Champion {incumbent['version_label']}; requiere aprobación manual.", "evidence": {"champion_wape": incumbent["wape"], "challenger_wape": champion["wape"]}},
                    "return=minimal",
                )
        else:
            db.request("PATCH", f"ml_model_versions?id=eq.{version_id}", {"state": "champion", "approved_at": now, "approved_by": run.get("requested_by")}, "return=minimal")

        final_status = payload["status"]
        db.patch_run(run_id, status=final_status, cutoff_period=payload["cutoff"] + "-01", engine_version=ENGINE_VERSION, completed_at=datetime.now(timezone.utc).isoformat())
        log(db, run_id, "completed", final_status, "Versión y evidencia persistidas", model_version_id=version_id, state="challenger" if current else "champion")
        print(json.dumps({"run_id": run_id, "model_version_id": version_id, "status": final_status, "state": "challenger" if current else "champion"}))
    except Exception as error:
        db.patch_run(run_id, status="error", error_detail={"type": type(error).__name__, "message": str(error)[:2000]})
        log(db, run_id, "error", "failed", "El entrenamiento no alteró el Champion", error=str(error)[:2000])
        raise


if __name__ == "__main__":
    try:
        main()
    except KeyError as error:
        sys.exit(f"Missing environment variable: {error.args[0]}")
