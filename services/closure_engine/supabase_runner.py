"""Asynchronous Supabase adapter for PRD 06.

Required environment: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
PERIOD_CLOSURE_ID.  Closing the real period and writing its immutable snapshot is
the transaction boundary: later learning failures are recorded and reprocessable
without replacing the Champion or Forecast Towell publication.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from engine import ActualRecord, ClosureConfig, FrozenForecast, HistoricalMetric, run_closure


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

    def patch(self, table: str, record_id: str, payload: dict) -> None:
        self.request("PATCH", f"{table}?id=eq.{record_id}", payload, "return=minimal")


def encoded(params: dict[str, str]) -> str:
    return urllib.parse.urlencode(params, safe="(),.*")


def audit(db: Supabase, closure_id: str, action: str, actor_id: str | None = None, reason: str | None = None, **new_value) -> None:
    db.request("POST", "closure_audit_log", {"period_closure_id": closure_id, "actor_id": actor_id, "action": action, "new_value": new_value or None, "reason": reason}, "return=minimal")


def sum_or_none(rows: list[dict], key: str = "quantity") -> float | None:
    return None if not rows else sum(float(row[key]) for row in rows)


def load_actuals(db: Supabase, closure: dict, period: dict) -> list[ActualRecord]:
    period_id = period["id"]
    org, chain = closure["organization_id"], closure["chain_id"]
    sales = db.request("GET", "sales?" + encoded({"period_id": f"eq.{period_id}", "organization_id": f"eq.{org}", "chain_id": f"eq.{chain}", "state": "eq.current", "status": "eq.final", "select": "product_id,quantity"})) or []
    orders = db.request("GET", "orders?" + encoded({"period_id": f"eq.{period_id}", "organization_id": f"eq.{org}", "chain_id": f"eq.{chain}", "state": "eq.current", "select": "id"})) or []
    order_ids = [row["id"] for row in orders]
    order_lines = db.request("GET", "order_lines?" + encoded({"order_id": f"in.({','.join(order_ids)})", "select": "id,product_id,quantity"})) if order_ids else []
    order_lines = order_lines or []
    line_ids = [row["id"] for row in order_lines]
    deliveries = db.request("GET", "deliveries?" + encoded({"order_line_id": f"in.({','.join(line_ids)})", "state": "eq.current", "select": "order_line_id,quantity"})) if line_ids else []
    deliveries = deliveries or []
    clients = db.request("GET", "customer_forecasts?" + encoded({"period_id": f"eq.{period_id}", "organization_id": f"eq.{org}", "chain_id": f"eq.{chain}", "state": "eq.current", "select": "product_id,quantity"})) or []
    products = db.request("GET", "products?" + encoded({"organization_id": f"eq.{org}", "family": "eq.FENDI", "select": "id,description,active"})) or []
    product_ids = [row["id"] for row in products]
    variants = db.request("GET", "product_variants?" + encoded({"product_id": f"in.({','.join(product_ids)})", "select": "product_id,color"})) if product_ids else []
    color = {row["product_id"]: row.get("color") or "Sin color" for row in (variants or [])}
    delivery_by_line: dict[str, list[dict]] = defaultdict(list)
    for row in deliveries:
        delivery_by_line[row["order_line_id"]].append(row)
    configuration = closure.get("configuration") or {}
    missing_client_ok = bool(configuration.get("client_forecast_not_received"))
    output = []
    for product in products:
        product_id = product["id"]
        product_sales = [row for row in sales if row["product_id"] == product_id]
        product_lines = [row for row in order_lines if row["product_id"] == product_id]
        product_deliveries = [item for line in product_lines for item in delivery_by_line.get(line["id"], [])]
        product_clients = [row for row in clients if row["product_id"] == product_id]
        output.append(ActualRecord(
            product_id, period["period_start"][:7], sum_or_none(product_sales), sum_or_none(product_lines), sum_or_none(product_deliveries),
            sum_or_none(product_clients), missing_client_ok and not product_clients, bool(product["active"]), "FENDI BD", color.get(product_id, "Sin color"),
        ))
    return output


def load_forecasts(db: Supabase, closure: dict, period: dict, actuals: list[ActualRecord]) -> tuple[list[FrozenForecast], str | None]:
    target_date = period["period_start"]
    vintage_rows = db.request("GET", "forecast_vintages?" + encoded({"forecast_date": f"eq.{target_date}", "select": "id,forecast_towell_id,product_id,issued_at,horizon,statistical_value,ml_value,value"})) or []
    version_ids = sorted({row["forecast_towell_id"] for row in vintage_rows})
    versions = db.request("GET", "forecast_towell?" + encoded({"id": f"in.({','.join(version_ids)})", "state": "eq.champion", "select": "id,version_label,state,created_at"})) if version_ids else []
    versions = versions or []
    by_version = {row["id"]: row for row in versions}
    bands_by_vintage = {}
    vintage_ids = [row["id"] for row in vintage_rows]
    if vintage_ids:
        bands = db.request("GET", "probability_bands?" + encoded({"forecast_vintage_id": f"in.({','.join(vintage_ids)})", "select": "forecast_vintage_id,p10,p50,p90,p95"})) or []
        bands_by_vintage = {row["forecast_vintage_id"]: row for row in bands}
    output: list[FrozenForecast] = []
    used_champion = None
    selected_rows: dict[tuple[str, int], dict] = {}
    for row in vintage_rows:
        version = by_version.get(row["forecast_towell_id"])
        if not version or not row.get("product_id"):
            continue
        key = (row["product_id"], int(row["horizon"]))
        previous = selected_rows.get(key)
        if previous is None or by_version[previous["forecast_towell_id"]]["created_at"] < version["created_at"]:
            selected_rows[key] = row
    for row in selected_rows.values():
        version = by_version.get(row["forecast_towell_id"])
        if not version or not row.get("product_id"):
            continue
        issued = row.get("issued_at") or version["created_at"]
        band = bands_by_vintage.get(row["id"], {})
        common = dict(series_id=row["product_id"], target_period=target_date[:7], version=version["version_label"], issued_at=issued, horizon=int(row["horizon"]), frozen=True)
        output.append(FrozenForecast(engine="statistical", value=float(row["statistical_value"]), **common))
        if row.get("ml_value") is not None:
            output.append(FrozenForecast(engine="ml", value=float(row["ml_value"]), **common))
            output.append(FrozenForecast(engine="challenger", value=float(row["ml_value"]), **common))
        output.append(FrozenForecast(engine="towell", value=float(row["value"]), p10=band.get("p10"), p50=band.get("p50"), p90=band.get("p90"), p95=band.get("p95"), **common))
        if version["state"] == "champion":
            used_champion = version["id"]
    for actual in actuals:
        if actual.client_forecast is not None:
            output.append(FrozenForecast(actual.series_id, target_date[:7], "client", "customer-forecast", f"{_previous_month(target_date[:7])}-01T00:00:00+00:00", 1, actual.client_forecast))
    return output, used_champion


def _previous_month(period: str) -> str:
    year, month = map(int, period.split("-"))
    month -= 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def load_history(db: Supabase, closure: dict) -> tuple[list[HistoricalMetric], dict[str, list[float]]]:
    closures = db.request("GET", "period_closures?" + encoded({"organization_id": f"eq.{closure['organization_id']}", "status": "in.(closed,completed,completed_with_learning_error)", "select": "id,period_id,revision"})) or []
    period_ids = sorted({row["period_id"] for row in closures})
    periods = db.request("GET", "periods?" + encoded({"id": f"in.({','.join(period_ids)})", "select": "id,period_start"})) if period_ids else []
    period_by_id = {row["id"]: row["period_start"][:7] for row in (periods or [])}
    closure_period = {row["id"]: period_by_id.get(row["period_id"]) for row in closures}
    closure_ids = [row["id"] for row in closures if closure_period.get(row["id"])]
    rows = db.request("GET", "forecast_accuracy?" + encoded({"period_closure_id": f"in.({','.join(closure_ids)})", "level": "eq.total", "dimension_key": "eq.total-fendi-bd", "select": "period_closure_id,engine,wape,bias"})) if closure_ids else []
    rows = rows or []
    history = []
    for row in rows:
        period = closure_period.get(row["period_closure_id"])
        if period:
            history.append(HistoricalMetric(period, row["engine"], float(row["wape"]), float(row["bias"])))
    realized = db.request("GET", "realized_metrics?" + encoded({"period_closure_id": f"in.({','.join(closure_ids)})", "select": "period_closure_id,series_key,sale"})) if closure_ids else []
    ordered_realized = sorted(realized or [], key=lambda row: (closure_period.get(row["period_closure_id"], ""), row["series_key"]))
    prior: dict[str, list[float]] = defaultdict(list)
    for row in ordered_realized:
        prior[row["series_key"]].append(float(row["sale"]))
    return history, dict(prior)


def persist_closed_snapshot(db: Supabase, closure: dict, period: dict, result: dict, champion_id: str | None) -> None:
    closure_id = closure["id"]
    realized_rows = [{
        "period_closure_id": closure_id, "series_key": row["series_id"], "category": row["category"], "color": row["color"],
        "sale": row["sale"], "ordered": row["order"], "delivered": row["delivery"], "client_forecast": row["client_forecast"],
        "client_forecast_not_received": row["client_forecast_not_received"], "active_at_close": row["active"],
        "product_id": row["series_id"],
    } for row in result["snapshot"]["realized"]]
    if realized_rows:
        db.request("POST", "realized_metrics", realized_rows, "resolution=ignore-duplicates,return=minimal")
    db.request("POST", "closure_snapshots", {"period_closure_id": closure_id, "snapshot_hash": result["snapshot_hash"], "payload": result["snapshot"]}, "resolution=ignore-duplicates,return=minimal")
    now = datetime.now(timezone.utc).isoformat()
    db.patch("period_closures", closure_id, {"status": "closed", "forecast_towell_id": champion_id, "champion_forecast_towell_id": champion_id, "closed_at": now, "validation": result["validation"]})
    db.patch("periods", period["id"], {"status": "closed", "closed_at": now, "closed_by": closure.get("requested_by")})
    audit(db, closure_id, "period.closed", closure.get("requested_by"), snapshot_hash=result["snapshot_hash"], champion_changed=False)


def persist_learning(db: Supabase, closure: dict, result: dict) -> None:
    closure_id = closure["id"]
    rolling = {row["engine"]: row for row in result["rolling_accuracy"]}
    forecast_rows = []
    for row in result["metrics"]:
        roll = rolling.get(row["engine"], {})
        forecast_rows.append({
            "period_closure_id": closure_id, "engine": row["engine"], "level": "total", "dimension_key": "total-fendi-bd",
            "forecast_version": ",".join(row["versions"]), "actual": row["actual_total"], "forecast": row["forecast_total"],
            "absolute_error": row["absolute_error"], "wape": row["wape"], "bias": row["bias"],
            "bias_direction": row["bias_direction"], "observations": row["observations"],
            "rolling_3_wape": roll.get("last_3", {}).get("wape"), "rolling_6_wape": roll.get("last_6", {}).get("wape"),
            "rolling_12_wape": roll.get("last_12", {}).get("wape"), "rolling_all_wape": roll.get("all", {}).get("wape"),
        })
    db.request("POST", "forecast_accuracy", forecast_rows, "resolution=ignore-duplicates,return=minimal")
    totals = result["totals"]
    db.request("POST", "fill_rate_metrics", {"period_closure_id": closure_id, "level": "total", "dimension_key": "total-fendi-bd", "ordered": totals["order"], "delivered": totals["delivery"], "sale": totals["sale"], "fill_rate": result["service"]["fill_rate"], "sale_to_order": result["service"]["sale_to_order"], "cause_attributed": False}, "resolution=ignore-duplicates,return=minimal")
    db.request("POST", "horizon_accuracy", [{"period_closure_id": closure_id, **row} for row in result["horizon_accuracy"]], "resolution=ignore-duplicates,return=minimal")
    coverage_rows = []
    for row in result["interval_coverage"]:
        calibration = "insufficient" if row["observations"] < 5 else "underestimated" if row["coverage_p90"] < 75 else "too_wide" if row["coverage_p90"] > 98 else "calibrated"
        coverage_rows.append({"period_closure_id": closure_id, **{key: row[key] for key in ("horizon","observations","coverage_p90","coverage_p95","below_p10","at_or_below_p50","outside_p95")}, "calibration_state": calibration, "evidence": {"evaluations": row["evaluations"]}})
    if coverage_rows:
        db.request("POST", "interval_coverage", coverage_rows, "resolution=ignore-duplicates,return=minimal")
    challenger = result["challenger_validation"]
    if challenger.get("current_champion_wape") is not None:
        state = challenger["state"]
        if state == "candidate_for_promotion" and challenger.get("evidence_sufficient"):
            stored_state = "candidate_for_promotion"
        elif state == "not_consistent":
            stored_state = "not_consistent"
        else:
            stored_state = "in_validation"
        db.request("POST", "challenger_validation", {
            "period_closure_id": closure_id, "champion_engine": "statistical", "challenger_engine": "ml_revalidated",
            "champion_wape": challenger["current_champion_wape"], "challenger_wape": challenger["current_challenger_wape"], "improvement_points": challenger["improvement_points"],
            "consecutive_wins": challenger["consecutive_wins"], "required_consecutive_wins": challenger["required_consecutive_wins"], "stable": challenger["stable"],
            "bias_controlled": True, "critical_horizons_pass": not bool(challenger["critical_horizon_degradation"]), "sufficient_observations": challenger["evidence_sufficient"],
            "state": stored_state, "automatic_promotion": False, "evidence": challenger,
        }, "resolution=ignore-duplicates,return=minimal")
    events = []
    for row in result["learning_events"]:
        event_type = row["type"]
        if event_type not in ("actuals_appended","retraining_requested","bimonthly_review","next_cycle_prepared","closure_corrected"):
            continue
        events.append({"period_closure_id": closure_id, "event_type": event_type, "status": row["status"], "payload": row})
    events += [{"period_closure_id": closure_id, "event_type": "drift_detected", "status": "observed", "severity": row["severity"], "payload": row} for row in result["drift"]]
    events += [{"period_closure_id": closure_id, "event_type": "persistent_bias", "status": "observed", "severity": "warning", "payload": row} for row in result["persistent_bias"]]
    if events:
        db.request("POST", "learning_events", events, "return=minimal")
    now = datetime.now(timezone.utc).isoformat()
    db.patch("period_closures", closure_id, {"status": "completed", "completed_at": now, "error_detail": None})
    audit(db, closure_id, "learning.completed", closure.get("requested_by"), challenger_state=challenger.get("state"), automatic_promotion=False)


def main() -> None:
    db, closure_id = Supabase(), os.environ["PERIOD_CLOSURE_ID"]
    rows = db.request("GET", f"period_closures?id=eq.{closure_id}&select=*&limit=1") or []
    if not rows:
        raise RuntimeError("period closure not found")
    closure = rows[0]
    periods = db.request("GET", f"periods?id=eq.{closure['period_id']}&select=*&limit=1") or []
    if not periods:
        raise RuntimeError("period not found")
    period = periods[0]
    db.patch("period_closures", closure_id, {"status": "closing", "started_at": datetime.now(timezone.utc).isoformat()})
    audit(db, closure_id, "closure.processing", closure.get("requested_by"))
    actuals = load_actuals(db, closure, period)
    frozen, champion_id = load_forecasts(db, closure, period, actuals)
    history, prior_sales = load_history(db, closure)
    configuration = closure.get("configuration") or {}
    allowed = {key: value for key, value in configuration.items() if key in ClosureConfig.__dataclass_fields__}
    previous_snapshot_hash = None
    if closure.get("previous_closure_id"):
        previous = db.request("GET", f"closure_snapshots?period_closure_id=eq.{closure['previous_closure_id']}&select=snapshot_hash&limit=1") or []
        previous_snapshot_hash = previous[0]["snapshot_hash"] if previous else None
    result = run_closure(period["period_start"][:7], actuals, frozen, history, prior_sales, ClosureConfig(**allowed), closure["revision"], previous_snapshot_hash, closure.get("correction_reason"), str(closure.get("requested_by") or "system"))
    if result["status"] == "blocked":
        db.patch("period_closures", closure_id, {"status": "failed_validation", "validation": result["validation"], "error_detail": {"stage": "validation", "blockers": result["validation"]["blockers"]}})
        db.patch("periods", period["id"], {"status": "validating"})
        audit(db, closure_id, "closure.validation_failed", closure.get("requested_by"), blockers=result["validation"]["blockers"])
        print(json.dumps({"closure_id": closure_id, "status": "failed_validation", "blockers": result["validation"]["blockers"]}))
        return
    persist_closed_snapshot(db, closure, period, result, champion_id)
    try:
        persist_learning(db, closure, result)
        print(json.dumps({"closure_id": closure_id, "status": "completed", "snapshot_hash": result["snapshot_hash"], "champion_changed": False}))
    except Exception as error:
        db.patch("period_closures", closure_id, {"status": "completed_with_learning_error", "completed_at": datetime.now(timezone.utc).isoformat(), "error_detail": {"stage": "learning", "type": type(error).__name__, "message": str(error)[:2000], "reprocessable": True}})
        db.request("POST", "learning_events", {"period_closure_id": closure_id, "event_type": "learning_failed", "status": "failed", "severity": "warning", "payload": {"message": str(error)[:2000], "champion_changed": False, "forecast_towell_changed": False}}, "return=minimal")
        audit(db, closure_id, "learning.failed", closure.get("requested_by"), error=str(error)[:2000], champion_changed=False)
        print(json.dumps({"closure_id": closure_id, "status": "completed_with_learning_error", "reprocessable": True, "champion_changed": False}))


if __name__ == "__main__":
    try:
        main()
    except KeyError as error:
        sys.exit(f"Missing environment variable: {error.args[0]}")
