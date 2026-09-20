"""PRD 07 controlled managerial decision and Forecast Value Added engine.

The mathematical Forecast Towell is input-only.  Every human decision produces
an immutable version that can later be evaluated independently against actuals.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from statistics import mean
from typing import Any


ENGINE_VERSION = "prd07-1.0.0"
ADJUSTMENT_REASONS = {
    "promotion", "customer_store_opening", "customer_store_closure", "confirmed_commercial_change",
    "extraordinary_order", "special_event", "discontinuation", "distribution_change",
    "commercial_restriction", "direct_customer_information", "business_correction", "other",
    "no_adjustment",
}
METHODS = {"absolute", "percentage", "final_value", "none"}


@dataclass(frozen=True)
class ForecastPoint:
    series_id: str
    target_period: str
    horizon: int
    towell_value: float
    vintage_id: str
    forecast_towell_version: str
    issued_at: str
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    category: str = "FENDI BD"
    color: str = "Sin color"


@dataclass(frozen=True)
class AdjustmentProposal:
    series_id: str
    horizon: int
    method: str
    value: float
    reason: str
    explanation: str
    evidence_reference: str | None = None


@dataclass(frozen=True)
class DecisionConfig:
    significant_adjustment_percent: float = 20.0
    fva_neutral_tolerance_points: float = 0.25
    require_separate_approver: bool = False
    allow_outside_p95_for_roles: tuple[str, ...] = ("manager",)


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _wape(actual: list[float], forecast: list[float]) -> float:
    denominator = sum(abs(value) for value in actual)
    numerator = sum(abs(a - f) for a, f in zip(actual, forecast))
    if denominator == 0:
        return 0.0 if numerator == 0 else 100.0
    return numerator / denominator * 100.0


def _bias(actual: list[float], forecast: list[float]) -> float:
    denominator = sum(abs(value) for value in actual)
    numerator = sum(f - a for a, f in zip(actual, forecast))
    if denominator == 0:
        return 0.0 if numerator == 0 else (100.0 if numerator > 0 else -100.0)
    return numerator / denominator * 100.0


def _decision_hash(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(stable.encode("utf-8")).hexdigest()


def _adjusted_value(base: float, proposal: AdjustmentProposal) -> float:
    if proposal.method == "none":
        return base
    if proposal.method == "absolute":
        return base + proposal.value
    if proposal.method == "percentage":
        return base * (1.0 + proposal.value / 100.0)
    if proposal.method == "final_value":
        return proposal.value
    raise ValueError("invalid_adjustment_method")


def create_decision(
    points: list[ForecastPoint],
    proposals: list[AdjustmentProposal],
    actor_id: str,
    actor_role: str,
    prior_versions: int = 0,
    config: DecisionConfig | None = None,
    previous_decision_hash: str | None = None,
    correction_reason: str | None = None,
    period_reopened: bool = False,
    previous_frozen: bool = False,
) -> dict[str, Any]:
    config = config or DecisionConfig()
    blockers: list[str] = []
    warnings: list[str] = []
    if actor_role not in ("manager", "editor"):
        blockers.append("proposal_role_required")
    if not points:
        blockers.append("forecast_towell_not_found")
    periods = {point.target_period[:7] for point in points}
    if len(periods) != 1:
        blockers.append("single_target_period_required")
    point_by_key = {(point.series_id, point.horizon): point for point in points}
    proposal_by_key: dict[tuple[str, int], AdjustmentProposal] = {}
    for proposal in proposals:
        key = (proposal.series_id, proposal.horizon)
        if key in proposal_by_key:
            blockers.append(f"duplicate_adjustment:{proposal.series_id}:h{proposal.horizon}")
        proposal_by_key[key] = proposal
        if key not in point_by_key:
            blockers.append(f"forecast_point_not_found:{proposal.series_id}:h{proposal.horizon}")
        if proposal.method not in METHODS:
            blockers.append(f"invalid_method:{proposal.series_id}:h{proposal.horizon}")
        if proposal.reason not in ADJUSTMENT_REASONS:
            blockers.append(f"invalid_reason:{proposal.series_id}:h{proposal.horizon}")
        if proposal.method != "none" and (not proposal.explanation or not proposal.explanation.strip()):
            blockers.append(f"explanation_required:{proposal.series_id}:h{proposal.horizon}")
        if proposal.method == "none" and proposal.reason != "no_adjustment":
            blockers.append(f"no_adjustment_reason_required:{proposal.series_id}:h{proposal.horizon}")
    if previous_frozen and not period_reopened:
        blockers.append("frozen_decision_requires_reopening")
    if prior_versions > 0 and correction_reason is not None and not correction_reason.strip():
        blockers.append("correction_reason_required")

    entries: list[dict[str, Any]] = []
    governance_alerts: list[dict[str, Any]] = []
    for key, point in sorted(point_by_key.items()):
        proposal = proposal_by_key.get(key) or AdjustmentProposal(point.series_id, point.horizon, "none", 0.0, "no_adjustment", "Revisado sin ajuste.")
        try:
            adjusted = _adjusted_value(point.towell_value, proposal)
        except ValueError as error:
            blockers.append(f"{error}:{point.series_id}:h{point.horizon}")
            adjusted = point.towell_value
        if adjusted < 0:
            blockers.append(f"negative_adjusted_forecast:{point.series_id}:h{point.horizon}")
        delta = adjusted - point.towell_value
        percent = 0.0 if point.towell_value == 0 and delta == 0 else None if point.towell_value == 0 else delta / point.towell_value * 100.0
        outside_p95 = point.p95 is not None and adjusted > point.p95
        below_p10 = point.p10 is not None and adjusted < point.p10
        within_p90 = point.p90 is not None and (point.p10 if point.p10 is not None else 0) <= adjusted <= point.p90
        significant = percent is None or abs(percent) >= config.significant_adjustment_percent
        if outside_p95 or below_p10:
            governance_alerts.append({"type": "outside_probability_range", "series_id": point.series_id, "horizon": point.horizon, "adjusted": _round(adjusted), "p10": point.p10, "p95": point.p95})
            if actor_role not in config.allow_outside_p95_for_roles:
                blockers.append(f"outside_band_authorization_required:{point.series_id}:h{point.horizon}")
        if significant and delta != 0:
            governance_alerts.append({"type": "significant_adjustment", "series_id": point.series_id, "horizon": point.horizon, "adjustment_percent": _round(percent), "threshold": config.significant_adjustment_percent})
        entries.append({
            "series_id": point.series_id,
            "category": point.category,
            "color": point.color,
            "horizon": point.horizon,
            "vintage_id": point.vintage_id,
            "forecast_towell_version": point.forecast_towell_version,
            "forecast_towell": _round(point.towell_value),
            "adjustment": _round(delta),
            "adjustment_percent": _round(percent),
            "forecast_adjusted": _round(adjusted),
            "forecast_approved": None,
            "method": proposal.method,
            "reason": proposal.reason,
            "explanation": proposal.explanation.strip() or "Revisado sin ajuste.",
            "evidence_reference": proposal.evidence_reference,
            "within_p90": within_p90,
            "outside_p95": outside_p95,
            "below_p10": below_p10,
            "significant_adjustment": significant and delta != 0,
            "bands": {"p10": point.p10, "p50": point.p50, "p90": point.p90, "p95": point.p95},
        })
    if blockers:
        return {"status": "blocked", "blockers": sorted(set(blockers)), "warnings": warnings, "forecast_towell_changed": False}

    target_period = next(iter(periods))
    revision = prior_versions + 1
    version = f"DEC-FENDI-{target_period}-V{revision:02d}"
    has_adjustment = any(entry["adjustment"] != 0 for entry in entries)
    payload = {
        "decision_version": version,
        "target_period": target_period,
        "revision": revision,
        "status": "adjusted" if has_adjustment else "reviewed",
        "actor_id": actor_id,
        "actor_role": actor_role,
        "entries": entries,
        "governance_alerts": governance_alerts,
        "previous_decision_hash": previous_decision_hash,
        "correction_reason": correction_reason,
        "source_contract": "normalized_platform_records",
        "forecast_towell_changed": False,
        "champion_challenger_affected": False,
        "generative_ai_used": False,
        "engine_version": ENGINE_VERSION,
    }
    return {**payload, "status": payload["status"], "decision_hash": _decision_hash(payload), "blockers": [], "warnings": warnings}


def approve_decision(decision: dict[str, Any], approver_id: str, approver_role: str, config: DecisionConfig | None = None, freeze: bool = True) -> dict[str, Any]:
    config = config or DecisionConfig()
    if decision.get("status") not in ("reviewed", "adjusted", "proposed"):
        return {"status": "blocked", "blockers": ["decision_not_approvable"], "forecast_towell_changed": False}
    if approver_role != "manager":
        return {"status": "blocked", "blockers": ["manager_approval_required"], "forecast_towell_changed": False}
    if config.require_separate_approver and decision.get("actor_id") == approver_id:
        return {"status": "blocked", "blockers": ["separate_approver_required"], "forecast_towell_changed": False}
    approved_entries = [{**entry, "forecast_approved": entry["forecast_adjusted"]} for entry in decision["entries"]]
    payload = {
        **{key: value for key, value in decision.items() if key not in ("entries", "decision_hash", "status")},
        "status": "frozen" if freeze else "approved",
        "entries": approved_entries,
        "approved_by": approver_id,
        "frozen": freeze,
        "forecast_towell_changed": False,
        "champion_challenger_affected": False,
    }
    return {**payload, "decision_hash": _decision_hash(payload), "blockers": []}


def evaluate_decision(decision: dict[str, Any], actuals: dict[str, float], neutral_tolerance_points: float = 0.25) -> dict[str, Any]:
    if decision.get("status") not in ("approved", "frozen", "evaluated"):
        return {"status": "blocked", "blockers": ["approved_decision_required"], "originals_protected": True}
    rows = [entry for entry in decision["entries"] if entry["series_id"] in actuals]
    if not rows:
        return {"status": "blocked", "blockers": ["actuals_not_found"], "originals_protected": True}
    actual = [float(actuals[row["series_id"]]) for row in rows]
    towell = [float(row["forecast_towell"]) for row in rows]
    approved = [float(row["forecast_approved"]) for row in rows]
    towell_wape = _wape(actual, towell)
    approved_wape = _wape(actual, approved)
    fva_points = towell_wape - approved_wape
    intervention = any(row["adjustment"] != 0 for row in rows)
    classification = "no_intervention" if not intervention else "positive" if fva_points > neutral_tolerance_points else "negative" if fva_points < -neutral_tolerance_points else "neutral"
    details = []
    for row in rows:
        real = float(actuals[row["series_id"]])
        base_error = abs(real - float(row["forecast_towell"]))
        approved_error = abs(real - float(row["forecast_approved"]))
        value = base_error - approved_error
        details.append({
            "series_id": row["series_id"], "horizon": row["horizon"], "reason": row["reason"], "actor_id": decision["actor_id"],
            "forecast_towell": row["forecast_towell"], "forecast_approved": row["forecast_approved"], "actual": real,
            "towell_absolute_error": _round(base_error), "approved_absolute_error": _round(approved_error), "fva_absolute": _round(value),
            "classification": "positive" if value > 0 else "negative" if value < 0 else "neutral",
        })
    by_reason = []
    for reason in sorted({row["reason"] for row in details}):
        subset = [row for row in details if row["reason"] == reason]
        by_reason.append({"reason": reason, "observations": len(subset), "average_fva_absolute": _round(mean(row["fva_absolute"] for row in subset)), "positive_rate": _round(mean(1 if row["fva_absolute"] > 0 else 0 for row in subset) * 100)})
    by_horizon = []
    for horizon in sorted({row["horizon"] for row in details}):
        subset = [row for row in details if row["horizon"] == horizon]
        by_horizon.append({"horizon": horizon, "observations": len(subset), "average_fva_absolute": _round(mean(row["fva_absolute"] for row in subset))})
    return {
        "status": "evaluated",
        "decision_version": decision["decision_version"],
        "towell_wape": _round(towell_wape),
        "approved_wape": _round(approved_wape),
        "towell_bias": _round(_bias(actual, towell)),
        "approved_bias": _round(_bias(actual, approved)),
        "fva_points": _round(fva_points),
        "classification": classification,
        "intervention": intervention,
        "details": details,
        "by_reason": by_reason,
        "by_horizon": by_horizon,
        "learning_event": {"type": "human_decision_evaluated", "model_training_allowed": False, "evidence_accumulated": True},
        "champion_challenger_affected": False,
        "forecast_towell_changed": False,
        "originals_protected": True,
        "reprocessable": True,
    }


def payload_from_dict(payload: dict[str, Any]) -> dict[str, Any]:
    points = [ForecastPoint(**row) for row in payload["points"]]
    proposals = [AdjustmentProposal(**row) for row in payload.get("proposals", [])]
    config_payload = payload.get("configuration", {})
    if "allow_outside_p95_for_roles" in config_payload:
        config_payload["allow_outside_p95_for_roles"] = tuple(config_payload["allow_outside_p95_for_roles"])
    decision = create_decision(points, proposals, payload["actor_id"], payload["actor_role"], int(payload.get("prior_versions", 0)), DecisionConfig(**config_payload), payload.get("previous_decision_hash"), payload.get("correction_reason"), bool(payload.get("period_reopened", False)), bool(payload.get("previous_frozen", False)))
    if decision["status"] == "blocked" or not payload.get("approve"):
        return decision
    approval = payload["approve"]
    approved = approve_decision(decision, approval["actor_id"], approval["actor_role"], DecisionConfig(**config_payload), bool(approval.get("freeze", True)))
    if approved["status"] == "blocked" or not payload.get("actuals"):
        return approved
    return {"decision": approved, "evaluation": evaluate_decision(approved, payload["actuals"], DecisionConfig(**config_payload).fva_neutral_tolerance_points)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a PRD 07 managerial decision from normalized records")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = payload_from_dict(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
