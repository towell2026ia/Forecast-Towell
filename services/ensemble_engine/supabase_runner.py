"""Asynchronous Supabase adapter for the PRD 05 ensemble engine.

Required environment: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, ENSEMBLE_RUN_ID.
The last valid publication remains active until every candidate, metric, vintage and
probability band has been persisted successfully.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from engine import (
    ENGINE_VERSION,
    EnsembleConfig,
    FutureRecord,
    build_common_backtest_records,
    ml_engine,
    run_ensemble,
)


class Supabase:
    def __init__(self) -> None:
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    def request(self, method: str, path: str, payload=None, prefer: str | None = None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(f"{self.url}/rest/v1/{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Supabase {method} {path}: {error.code} {detail}") from error

    def patch_run(self, run_id: str, **fields) -> None:
        self.request("PATCH", f"ensemble_runs?id=eq.{run_id}", fields, "return=minimal")


def audit(db: Supabase, run_id: str, stage: str, status: str, message: str, forecast_towell_id=None, **details) -> None:
    db.request("POST", "ensemble_audit_log", {"ensemble_run_id": run_id, "forecast_towell_id": forecast_towell_id, "stage": stage, "status": status, "message": message, "details": details}, "return=minimal")


def encoded(params: dict) -> str:
    return urllib.parse.urlencode(params, safe="(),.*")


def next_version(db: Supabase, organization_id: str, cutoff: str) -> str:
    prefix = f"FT-FENDI-{cutoff.replace('-', '')}-V"
    rows = db.request("GET", "forecast_towell?" + encoded({"organization_id": f"eq.{organization_id}", "version_label": f"like.{prefix}*", "select": "version_label"})) or []
    numbers = [int(match.group(1)) for row in rows if (match := re.search(r"-V(\d+)$", row["version_label"]))]
    return f"{prefix}{max(numbers, default=0) + 1:02d}"


def main() -> None:
    started = time.perf_counter()
    db, run_id = Supabase(), os.environ["ENSEMBLE_RUN_ID"]
    rows = db.request("GET", f"ensemble_runs?id=eq.{run_id}&select=*&limit=1")
    if not rows:
        raise RuntimeError("ensemble run not found")
    run = rows[0]
    target = run["target"]
    try:
        db.patch_run(run_id, status="preparing", started_at=datetime.now(timezone.utc).isoformat())
        audit(db, run_id, "preparing", "started", "Leyendo motores publicados y observaciones normalizadas")

        stat_runs = db.request("GET", "forecast_runs?" + encoded({
            "organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}", "target": f"eq.{target}",
            "status": "in.(completed,completed_with_alerts)", "frozen_at": "not.is.null", "select": "id,version_label,cutoff_period", "order": "completed_at.desc", "limit": "1",
        })) or []
        if not stat_runs:
            raise ValueError("No existe Champion estadístico válido")
        stat_run = stat_runs[0]
        cutoff = stat_run["cutoff_period"][:7]
        stat_results = db.request("GET", f"forecast_results?run_id=eq.{stat_run['id']}&select=id,series_id,winning_model,wape,bias,stability") or []
        series_rows = db.request("GET", "forecast_series?" + encoded({
            "organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}", "target": f"eq.{target}",
            "select": "id,product_id,grain,label",
        })) or []
        series_by_id = {row["id"]: row for row in series_rows}
        stat_models: dict[str, str] = {}
        future_by_key: dict[tuple[str, str], FutureRecord] = {}
        for result in stat_results:
            definition = series_by_id.get(result["series_id"])
            if not definition:
                continue
            series_key = "total-fendi-bd" if definition["grain"] == "total" else definition["product_id"]
            stat_models[series_key] = result.get("winning_model") or "Naive"
            values = db.request("GET", f"forecast_values?forecast_result_id=eq.{result['id']}&select=period_start,horizon,value&order=horizon.asc") or []
            for value in values:
                period = value["period_start"][:7]
                future_by_key[(series_key, period)] = FutureRecord(series_key, definition["label"], period, int(value["horizon"]), float(value["value"]), None)

        ml_versions = db.request("GET", "ml_model_versions?" + encoded({
            "organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}", "target": f"eq.{target}",
            "state": "eq.champion", "select": "id,version_label,algorithm,wape", "order": "created_at.desc", "limit": "1",
        })) or []
        ml_version = ml_versions[0] if ml_versions else None
        ml_failed = False
        if ml_version:
            predictions = db.request("GET", f"ml_predictions?model_version_id=eq.{ml_version['id']}&select=product_id,forecast_date,horizon,value") or []
            for prediction in predictions:
                series_key = prediction["product_id"] or "total-fendi-bd"
                key = (series_key, prediction["forecast_date"][:7])
                if key in future_by_key:
                    current = future_by_key[key]
                    future_by_key[key] = FutureRecord(current.series_id, current.label, current.period, current.horizon, current.statistical, float(prediction["value"]))

        value_column = "sale" if target == "Venta" else "orders"
        observations = db.request("GET", "ml_training_observations?" + encoded({
            "organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}",
            "select": f"product_id,description,color,category,period_start,{value_column}", "order": "period_start.asc",
        })) or []
        grouped: dict[str, ml_engine.Series] = {}
        for row in observations:
            product_id = row["product_id"]
            series = grouped.setdefault(product_id, ml_engine.Series(product_id, row.get("description") or product_id, row.get("color") or "Sin color", row.get("category") or "Sin categoría", {}))
            value = row.get(value_column)
            series.points[row["period_start"][:7]] = None if value is None else float(value)
        if not grouped:
            raise ValueError("No existen registros normalizados para el ensamble")

        db.patch_run(run_id, status="calculating")
        factory = ml_engine.MODEL_FACTORIES.get(ml_version["algorithm"]) if ml_version else None
        try:
            records = build_common_backtest_records(list(grouped.values()), stat_models, factory)
        except Exception as error:
            ml_failed = True
            records = build_common_backtest_records(list(grouped.values()), stat_models, None)
            audit(db, run_id, "calculating", "fallback", "ML falló; se conservó el motor estadístico", error=str(error)[:1000])
        if ml_version and not any(record.ml is not None for record in records):
            ml_failed = True
            audit(db, run_id, "calculating", "fallback", "ML no produjo ventanas comparables; se conservó el motor estadístico")

        db.patch_run(run_id, status="evaluating")
        total_result = next((result for result in stat_results if series_by_id.get(result["series_id"], {}).get("grain") == "total"), None)
        config = EnsembleConfig(minimum_improvement=float(run["minimum_improvement"]), reference_champion_wape=float(total_result["wape"]) if total_result and total_result.get("wape") is not None else 24.0)
        payload = run_ensemble(records, list(future_by_key.values()), cutoff, stat_run["version_label"], ml_version["version_label"] if ml_version else None, config, target, float(total_result["wape"]) if total_result and total_result.get("wape") is not None else None, float(ml_version["wape"]) if ml_version and ml_version.get("wape") is not None else None)
        if payload.get("status") == "insufficient":
            raise ValueError(payload["reason"])

        series_id_by_key = {("total-fendi-bd" if row["grain"] == "total" else row["product_id"]): row["id"] for row in series_rows}
        candidate_ids: dict[tuple[float, float], str] = {}
        for candidate in payload["selection"]["candidates"]:
            candidate_row = db.request("POST", "ensemble_candidates", {
                "ensemble_run_id": run_id,
                **{key: candidate[key] for key in ("strategy","statistical_weight","ml_weight","score","wape","bias","stability","recent_wape","historical_wape","deterioration","observations","windows","no_degradation_pass","minimum_improvement_pass","state")},
                "rejection_reason": candidate.get("rejection_reason"),
            }, "return=representation")[0]
            candidate_ids[(candidate["statistical_weight"], candidate["ml_weight"])] = candidate_row["id"]
            metric_keys = ("observations","windows","wape","bias","stability","recent_wape","historical_wape","deterioration")
            metric_rows = [{"level": "global", "dimension_key": "global", **{key: candidate[key] for key in metric_keys}}]
            metric_rows += [{"level": "horizon", "dimension_key": f"horizon:{metric['horizon']}", "horizon": metric["horizon"], **{key: metric[key] for key in metric_keys}} for metric in candidate["by_horizon"]]
            metric_rows += [{"level": "series", "dimension_key": f"series:{metric['series_id']}", "forecast_series_id": series_id_by_key.get(metric["series_id"]), **{key: metric[key] for key in metric_keys}} for metric in candidate["by_series"]]
            for metric in metric_rows:
                db.request("POST", "ensemble_metrics", {"candidate_id": candidate_row["id"], **metric}, "return=minimal")

        official = payload["selection"]["official"]
        version_label = next_version(db, run["organization_id"], cutoff)
        confidence_order = {"Baja": 0, "Media": 1, "Alta": 2}
        confidence = min((row["confidence"] for row in payload["forecast_towell"]), key=lambda value: confidence_order[value], default="Baja")
        version = db.request("POST", "forecast_towell", {
            "ensemble_run_id": run_id, "organization_id": run["organization_id"], "chain_id": run["chain_id"], "target": target,
            "version_label": version_label, "state": "challenger", "cutoff_period": cutoff + "-01", "statistical_run_id": stat_run["id"],
            "ml_model_version_id": ml_version["id"] if ml_version else None, "strategy": official["strategy"],
            "statistical_weight": official["statistical_weight"], "ml_weight": official["ml_weight"], "wape": official["wape"], "bias": official["bias"],
            "stability": official["stability"], "minimum_improvement": config.minimum_improvement,
            "improvement_points": payload["selection"]["improvement_points"], "confidence": confidence, "created_by": run.get("requested_by"),
        }, "return=representation")[0]
        version_id = version["id"]

        for forecast in payload["forecast_towell"]:
            product_id = None if forecast["series_id"] == "total-fendi-bd" else forecast["series_id"]
            vintage = db.request("POST", "forecast_vintages", {
                "forecast_towell_id": version_id, "forecast_series_id": series_id_by_key.get(forecast["series_id"]), "product_id": product_id,
                "forecast_date": forecast["period"] + "-01", "horizon": forecast["horizon"], "statistical_value": forecast["statistical"], "ml_value": forecast["ml"],
                "statistical_weight": forecast["statistical_weight"], "ml_weight": forecast["ml_weight"], "raw_value": forecast["raw_value"],
                "value": forecast["value"], "operational_value": forecast["operational_value"], "divergence": forecast["divergence"], "confidence": forecast["confidence"],
                "adjustment": {"negative_clamp": forecast["raw_value"] < 0},
            }, "return=representation")[0]
            db.request("POST", "probability_bands", {"forecast_vintage_id": vintage["id"], **forecast["probability"], "method": "empirical_oos_residuals"}, "return=minimal")

        for alert in payload["alerts"]:
            db.request("POST", "ensemble_alerts", {"ensemble_run_id": run_id, "forecast_towell_id": version_id, "alert_type": alert["type"], "severity": alert["severity"], "message": "Alta divergencia entre motores." if alert["type"] == "high_divergence" else "Forecast negativo ajustado trazablemente a cero.", "evidence": alert}, "return=minimal")
        if ml_failed or not ml_version:
            db.request("POST", "ensemble_alerts", {"ensemble_run_id": run_id, "forecast_towell_id": version_id, "alert_type": "ml_error", "severity": "warning", "message": "ML no estuvo disponible; Forecast Towell conservó el Champion estadístico.", "evidence": {"ml_version": ml_version}}, "return=minimal")
        if int(cutoff[-2:]) % 2 == 0:
            db.request("POST", "ensemble_alerts", {"ensemble_run_id": run_id, "forecast_towell_id": version_id, "alert_type": "bimonthly_review", "severity": "info", "message": "Corresponde revisión bimestral ampliada de motores, pesos, drift y error por horizonte.", "evidence": {"cutoff": cutoff}}, "return=minimal")

        now = datetime.now(timezone.utc).isoformat()
        db.request("PATCH", f"forecast_towell?id=eq.{version_id}", {"state": "champion", "published_by": run.get("requested_by"), "published_at": now}, "return=minimal")
        db.request("POST", "forecast_towell_publications", {"organization_id": run["organization_id"], "chain_id": run["chain_id"], "target": target, "forecast_towell_id": version_id, "published_by": run.get("requested_by"), "published_at": now}, "resolution=merge-duplicates,return=minimal")
        final_status = "challenger" if payload["selection"]["challenger"] else "champion"
        db.patch_run(run_id, status=final_status, cutoff_period=cutoff + "-01", engine_version=ENGINE_VERSION, configuration={**payload["configuration"], "duration_ms": round((time.perf_counter() - started) * 1000)}, completed_at=now)
        audit(db, run_id, "finalized", final_status, "Forecast Towell versionado sin degradar el Champion", version_id, version_label=version_label, strategy=official["strategy"], wape=official["wape"])
        print(json.dumps({"run_id": run_id, "forecast_towell_id": version_id, "version": version_label, "status": final_status, "strategy": official["strategy"]}))
    except Exception as error:
        db.patch_run(run_id, status="error", error_detail={"type": type(error).__name__, "message": str(error)[:2000]})
        audit(db, run_id, "error", "failed", "El error no reemplazó la última publicación válida", error=str(error)[:2000])
        raise


if __name__ == "__main__":
    try:
        main()
    except KeyError as error:
        sys.exit(f"Missing environment variable: {error.args[0]}")
