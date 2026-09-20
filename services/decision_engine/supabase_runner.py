"""Asynchronous PRD 07 FVA evaluator for a completed PRD 06 closure.

Required environment: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
PERIOD_CLOSURE_ID.  Failures never mutate Forecast Towell, the frozen decision,
the closure, or realized values; they only create reprocessable learning events.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from engine import evaluate_decision


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
            raise RuntimeError(f"Supabase {method} {path}: {error.code} {error.read().decode(errors='replace')}") from error


def encoded(params: dict[str, str]) -> str:
    return urllib.parse.urlencode(params, safe="(),.*")


def persist_evaluation(db: Supabase, closure_id: str, version: dict, adjustments: list[dict], evaluation: dict, reason_by_id: dict[str, str]) -> None:
    version_id = version["id"]
    total = {
        "period_closure_id": closure_id, "adjustment_version_id": version_id, "level": "total", "dimension_key": "total-fendi-bd",
        "observations": len(evaluation["details"]), "towell_wape": evaluation["towell_wape"], "approved_wape": evaluation["approved_wape"],
        "towell_bias": evaluation["towell_bias"], "approved_bias": evaluation["approved_bias"], "fva_points": evaluation["fva_points"],
        "classification": evaluation["classification"],
    }
    rows = [total]
    adjustment_by_key = {(row["product_id"], int(row["horizon"])): row for row in adjustments}
    for detail in evaluation["details"]:
        adjustment = adjustment_by_key[(detail["series_id"], int(detail["horizon"]))]
        rows.append({
            "period_closure_id": closure_id, "adjustment_version_id": version_id, "forecast_adjustment_id": adjustment["id"],
            "level": "series", "dimension_key": f"series:{detail['series_id']}:h{detail['horizon']}", "horizon": detail["horizon"],
            "reason_id": adjustment["reason_id"], "actor_id": version["proposed_by"], "observations": 1,
            "towell_absolute_error": detail["towell_absolute_error"], "approved_absolute_error": detail["approved_absolute_error"],
            "fva_absolute": detail["fva_absolute"], "classification": detail["classification"],
        })
    for item in evaluation["by_reason"]:
        reason_id = next((key for key, code in reason_by_id.items() if code == item["reason"]), None)
        rows.append({"period_closure_id": closure_id, "adjustment_version_id": version_id, "level": "reason", "dimension_key": f"reason:{item['reason']}", "reason_id": reason_id, "observations": item["observations"], "fva_absolute": item["average_fva_absolute"], "classification": "positive" if item["average_fva_absolute"] > 0 else "negative" if item["average_fva_absolute"] < 0 else "neutral"})
    for item in evaluation["by_horizon"]:
        rows.append({"period_closure_id": closure_id, "adjustment_version_id": version_id, "level": "horizon", "dimension_key": f"horizon:{item['horizon']}", "horizon": item["horizon"], "observations": item["observations"], "fva_absolute": item["average_fva_absolute"], "classification": "positive" if item["average_fva_absolute"] > 0 else "negative" if item["average_fva_absolute"] < 0 else "neutral"})
    rows.append({"period_closure_id": closure_id, "adjustment_version_id": version_id, "level": "user", "dimension_key": f"user:{version['proposed_by']}", "actor_id": version["proposed_by"], "observations": len(evaluation["details"]), "fva_points": evaluation["fva_points"], "classification": evaluation["classification"]})
    db.request("POST", "human_fva_metrics", rows, "resolution=ignore-duplicates,return=minimal")
    db.request("POST", "decision_learning_events", {
        "period_closure_id": closure_id, "adjustment_version_id": version_id, "event_type": "human_decision_evaluated", "status": "completed",
        "payload": {"towell_wape": evaluation["towell_wape"], "approved_wape": evaluation["approved_wape"], "fva_points": evaluation["fva_points"], "classification": evaluation["classification"], "model_training_allowed": False, "champion_challenger_affected": False},
    }, "return=minimal")
    if evaluation["classification"] == "negative":
        prior_negative = db.request("GET", "human_fva_metrics?" + encoded({"level": "eq.user", "actor_id": f"eq.{version['proposed_by']}", "classification": "eq.negative", "select": "id", "limit": "3"})) or []
        if len(prior_negative) >= 3:
            evidence = {"actor_id": version["proposed_by"], "negative_observations": len(prior_negative), "purpose": "process_review_not_person_rating"}
            db.request("POST", "decision_governance_alerts", {"adjustment_version_id": version_id, "alert_type": "negative_fva_pattern", "severity": "warning", "message": "Ajustes con FVA negativo reiterado; revisar el proceso y sus motivos.", "evidence": evidence}, "resolution=ignore-duplicates,return=minimal")
            db.request("POST", "decision_learning_events", {"period_closure_id": closure_id, "adjustment_version_id": version_id, "event_type": "negative_fva_pattern", "status": "observed", "payload": evidence}, "return=minimal")


def main() -> None:
    db, closure_id = Supabase(), os.environ["PERIOD_CLOSURE_ID"]
    closures = db.request("GET", f"period_closures?id=eq.{closure_id}&select=id,organization_id,period_id,status&limit=1") or []
    if not closures:
        raise RuntimeError("period closure not found")
    closure = closures[0]
    if closure["status"] not in ("closed", "completed", "completed_with_learning_error"):
        raise RuntimeError("closed period required")
    periods = db.request("GET", f"periods?id=eq.{closure['period_id']}&select=period_start&limit=1") or []
    if not periods:
        raise RuntimeError("period not found")
    target_date = periods[0]["period_start"]
    realized = db.request("GET", f"realized_metrics?period_closure_id=eq.{closure_id}&active_at_close=eq.true&select=product_id,sale") or []
    actuals = {row["product_id"]: float(row["sale"]) for row in realized if row.get("product_id")}
    vintages = db.request("GET", "forecast_vintages?" + encoded({"forecast_date": f"eq.{target_date}", "select": "id,product_id,horizon"})) or []
    vintage_by_id = {row["id"]: row for row in vintages}
    vintage_ids = list(vintage_by_id)
    if not vintage_ids:
        print(json.dumps({"closure_id": closure_id, "status": "no_decisions"}))
        return
    adjustments = db.request("GET", "forecast_adjustments?" + encoded({"forecast_vintage_id": f"in.({','.join(vintage_ids)})", "select": "id,adjustment_version_id,forecast_vintage_id,product_id,horizon,reason_id,forecast_towell,forecast_adjusted,adjustment"})) or []
    version_ids = sorted({row["adjustment_version_id"] for row in adjustments})
    if not version_ids:
        print(json.dumps({"closure_id": closure_id, "status": "no_decisions"}))
        return
    versions = db.request("GET", "adjustment_versions?" + encoded({"id": f"in.({','.join(version_ids)})", "state": "eq.frozen", "select": "id,forecast_decision_id,version_label,revision,proposed_by,state"})) or []
    latest: dict[str, dict] = {}
    for version in versions:
        current = latest.get(version["forecast_decision_id"])
        if current is None or int(version["revision"]) > int(current["revision"]):
            latest[version["forecast_decision_id"]] = version
    reasons = db.request("GET", "adjustment_reasons?select=id,code") or []
    reason_by_id = {row["id"]: row["code"] for row in reasons}
    completed, failed = [], []
    for version in latest.values():
        version_adjustments = [row for row in adjustments if row["adjustment_version_id"] == version["id"]]
        try:
            entries = [{
                "series_id": row["product_id"], "horizon": int(row["horizon"]), "reason": reason_by_id[row["reason_id"]],
                "forecast_towell": float(row["forecast_towell"]), "forecast_adjusted": float(row["forecast_adjusted"]),
                "forecast_approved": float(row["forecast_adjusted"]), "adjustment": float(row["adjustment"]),
            } for row in version_adjustments]
            decision = {"status": "frozen", "decision_version": version["version_label"], "actor_id": version["proposed_by"], "entries": entries}
            evaluation = evaluate_decision(decision, actuals)
            if evaluation["status"] == "blocked":
                raise ValueError(",".join(evaluation["blockers"]))
            persist_evaluation(db, closure_id, version, version_adjustments, evaluation, reason_by_id)
            completed.append({"version": version["version_label"], "fva_points": evaluation["fva_points"], "classification": evaluation["classification"]})
        except Exception as error:
            db.request("POST", "decision_learning_events", {"period_closure_id": closure_id, "adjustment_version_id": version["id"], "event_type": "fva_evaluation_failed", "status": "failed", "payload": {"message": str(error)[:2000], "reprocessable": True, "forecast_towell_changed": False, "decision_changed": False, "real_changed": False}}, "return=minimal")
            failed.append({"version": version["version_label"], "error": str(error)[:500]})
    print(json.dumps({"closure_id": closure_id, "status": "completed_with_errors" if failed else "completed", "evaluated": completed, "failed": failed, "originals_protected": True}))


if __name__ == "__main__":
    try:
        main()
    except KeyError as error:
        sys.exit(f"Missing environment variable: {error.args[0]}")
