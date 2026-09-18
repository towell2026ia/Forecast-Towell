"""Operational Supabase adapter for the deterministic PRD 03 engine.

Required environment: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, FORECAST_RUN_ID.
The adapter reads only closed monthly observations from the database view, writes all
model evidence, and freezes the run only after persistence succeeds.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from engine import ENGINE_VERSION, add_month, run_series


class Supabase:
    def __init__(self) -> None:
        self.url = os.environ["SUPABASE_URL"].rstrip("/")
        self.key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

    def request(self, method: str, path: str, payload=None, prefer: str | None = None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer: headers["Prefer"] = prefer
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(f"{self.url}/rest/v1/{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise RuntimeError(f"Supabase {method} {path}: {error.code} {detail}") from error

    def patch_run(self, run_id: str, **fields) -> None:
        self.request("PATCH", f"forecast_runs?id=eq.{run_id}", fields, "return=minimal")


def status(db: Supabase, run_id: str, value: str) -> None:
    db.patch_run(run_id, status=value)


def main() -> None:
    db, run_id = Supabase(), os.environ["FORECAST_RUN_ID"]
    run = db.request("GET", f"forecast_runs?id=eq.{run_id}&select=*&limit=1")
    if not run: raise RuntimeError("forecast run not found")
    run = run[0]
    target = run["target"]
    try:
        db.patch_run(run_id, status="preparing", started_at=datetime.now(timezone.utc).isoformat())
        query = urllib.parse.urlencode({"organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}", "target": f"eq.{target}", "select": "product_id,label,period_start,value", "order": "period_start.asc"})
        observations = db.request("GET", f"forecast_monthly_observations?{query}")
        status(db, run_id, "analyzing")
        grouped: dict[str, dict] = {}
        for row in observations:
            group = grouped.setdefault(row["product_id"], {"label": row["label"], "points": {}})
            group["points"][row["period_start"][:7]] = float(row["value"])
        status(db, run_id, "models")
        results = []
        for product_id, group in grouped.items():
            periods = sorted(group["points"])
            result = run_series(product_id, group["label"].replace("TOALLA MB FENDI ", "").title(), periods, [group["points"][p] for p in periods], target)
            result["product_id"] = product_id
            results.append(result)
        status(db, run_id, "backtesting")
        all_periods = sorted({p for group in grouped.values() for p in group["points"]})
        if all_periods:
            totals = [sum(group["points"].get(period, 0) for group in grouped.values()) for period in all_periods]
            results.insert(0, run_series("total-fendi-bd", "Total FENDI BD", all_periods, totals, target))
        status(db, run_id, "evaluating")
        last_period = max(all_periods) if all_periods else None
        for result in results:
            product_id = result.get("product_id")
            filters = urllib.parse.urlencode({"organization_id": f"eq.{run['organization_id']}", "chain_id": f"eq.{run['chain_id']}", "target": f"eq.{target}", "grain": f"eq.{'total' if product_id is None else 'product'}", "product_id": "is.null" if product_id is None else f"eq.{product_id}", "select": "id", "limit": "1"})
            existing = db.request("GET", f"forecast_series?{filters}")
            if existing: series_id = existing[0]["id"]
            else:
                created = db.request("POST", "forecast_series", {"organization_id": run["organization_id"], "chain_id": run["chain_id"], "target": target, "grain": "total" if product_id is None else "product", "product_id": product_id, "label": result["label"]}, "return=representation")
                series_id = created[0]["id"]
            result_row = db.request("POST", "forecast_results", {"run_id": run_id, "series_id": series_id, "result_status": result["status"], "classification": result.get("classification"), "winning_model": result.get("winner"), "wape": result.get("wape"), "bias": result.get("bias"), "stability": result.get("stability"), "diagnostics": result.get("diagnostics", {}), "explanation": result.get("explanation"), "reason": result.get("reason")}, "return=representation")[0]
            for comparison in result.get("comparisons", []):
                windows = comparison.pop("windows", [])
                model_row = db.request("POST", "forecast_model_results", {"forecast_result_id": result_row["id"], "model_name": comparison["model"], "applicable": comparison["applicable"], "wape": comparison.get("wape"), "bias": comparison.get("bias"), "stability": comparison.get("stability"), "score": comparison.get("score"), "parameters": {"horizon_metrics": windows}}, "return=representation")
                if not model_row:
                    raise RuntimeError("model result was not persisted")
            for point in result.get("forecast", []):
                period = point["period"] + "-01"
                horizon = ((int(point["period"][:4]) * 12 + int(point["period"][5:7])) - (int(last_period[:4]) * 12 + int(last_period[5:7]))) if last_period else 1
                db.request("POST", "forecast_values", {"forecast_result_id": result_row["id"], "period_start": period, "horizon": horizon, "value": point["forecast"]}, "return=minimal")
            for alert in result.get("alerts", []):
                db.request("POST", "statistical_alerts", {"forecast_result_id": result_row["id"], "alert_type": "wape_deterioration" if "precisión" in alert["type"] else "anomaly", "severity": "warning", "message": alert["message"]}, "return=minimal")
        status(db, run_id, "generating")
        sequence = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        final_status = "completed_with_alerts" if any(r.get("alerts") for r in results) else "completed"
        db.patch_run(run_id, status=final_status, version_label=f"FENDI-BD-{target}-{sequence}", cutoff_period=(last_period + "-01") if last_period else None, engine_version=ENGINE_VERSION, completed_at=datetime.now(timezone.utc).isoformat(), frozen_at=datetime.now(timezone.utc).isoformat())
        print(json.dumps({"run_id": run_id, "status": final_status, "series": len(results), "cutoff": last_period}))
    except Exception as error:
        db.patch_run(run_id, status="error", error_detail={"type": type(error).__name__, "message": str(error)[:2000]})
        raise


if __name__ == "__main__":
    try: main()
    except KeyError as error:
        sys.exit(f"Missing environment variable: {error.args[0]}")
