"""PRD 06 monthly closure, realized performance and learning engine.

The engine consumes the same normalized-record contract used by the platform.  It
never reads spreadsheets and it only evaluates immutable forecasts that were
issued before the target period closed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
from pathlib import Path
from statistics import mean, pstdev
from typing import Any, Iterable


ENGINE_VERSION = "prd06-1.0.0"
ENGINES = ("client", "statistical", "ml", "towell", "challenger")


@dataclass(frozen=True)
class ActualRecord:
    series_id: str
    period: str
    sale: float | None
    order: float | None
    delivery: float | None
    client_forecast: float | None
    client_forecast_not_received: bool = False
    active: bool = True
    category: str = "FENDI BD"
    color: str = "Sin color"


@dataclass(frozen=True)
class FrozenForecast:
    series_id: str
    target_period: str
    engine: str
    version: str
    issued_at: str
    horizon: int
    value: float
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    p95: float | None = None
    frozen: bool = True


@dataclass(frozen=True)
class HistoricalMetric:
    period: str
    engine: str
    wape: float
    bias: float
    observations: int = 1


@dataclass(frozen=True)
class ClosureConfig:
    minimum_improvement: float = 0.25
    challenger_periods_required: int = 3
    maximum_absolute_bias: float = 20.0
    maximum_challenger_wape_stddev: float = 8.0
    critical_horizons: tuple[int, ...] = (1, 2, 3)
    maximum_critical_horizon_degradation: float = 2.0
    drift_relative_change: float = 0.35
    retrain_deterioration_points: float = 5.0
    persistent_bias_periods: int = 4
    champion_reference_wape: float = 23.96
    challenger_reference_wape: float = 22.56


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _period_key(period: str) -> tuple[int, int]:
    year, month = period[:7].split("-")
    return int(year), int(month)


def _wape(actual: Iterable[float], forecast: Iterable[float]) -> float:
    pairs = list(zip(actual, forecast))
    denominator = sum(abs(a) for a, _ in pairs)
    numerator = sum(abs(a - f) for a, f in pairs)
    if denominator == 0:
        return 0.0 if numerator == 0 else 100.0
    return numerator / denominator * 100.0


def _bias(actual: Iterable[float], forecast: Iterable[float]) -> float:
    """Positive is overforecast; negative is underforecast."""
    pairs = list(zip(actual, forecast))
    denominator = sum(abs(a) for a, _ in pairs)
    numerator = sum(f - a for a, f in pairs)
    if denominator == 0:
        return 0.0 if numerator == 0 else (100.0 if numerator > 0 else -100.0)
    return numerator / denominator * 100.0


def _ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return 100.0 if numerator == 0 else None
    return numerator / denominator * 100.0


def validate_closure(records: list[ActualRecord], forecasts: list[FrozenForecast], period: str) -> ValidationResult:
    blockers: list[str] = []
    warnings: list[str] = []
    active = [row for row in records if row.period[:7] == period[:7] and row.active]
    if not active:
        blockers.append("period_without_active_series")

    seen: set[str] = set()
    for row in active:
        if row.series_id in seen:
            blockers.append(f"duplicate_series:{row.series_id}")
        seen.add(row.series_id)
        for field_name in ("sale", "order", "delivery"):
            value = getattr(row, field_name)
            if value is None:
                blockers.append(f"missing_{field_name}:{row.series_id}")
            elif value < 0:
                blockers.append(f"negative_{field_name}:{row.series_id}")
        if row.client_forecast is None and not row.client_forecast_not_received:
            blockers.append(f"missing_client_forecast_status:{row.series_id}")
        if row.client_forecast is not None and row.client_forecast < 0:
            blockers.append(f"negative_client_forecast:{row.series_id}")
        if row.order == 0 and row.delivery not in (None, 0):
            blockers.append(f"delivery_without_order:{row.series_id}")

    relevant = [f for f in forecasts if f.target_period[:7] == period[:7]]
    keys: set[tuple[str, str, int]] = set()
    for forecast in relevant:
        key = (forecast.series_id, forecast.engine, forecast.horizon)
        if key in keys:
            blockers.append(f"duplicate_vintage:{forecast.series_id}:{forecast.engine}:h{forecast.horizon}")
        keys.add(key)
        if forecast.engine not in ENGINES:
            blockers.append(f"unknown_engine:{forecast.engine}")
        if not forecast.frozen:
            blockers.append(f"unfrozen_forecast:{forecast.series_id}:{forecast.engine}")
        if not 1 <= forecast.horizon <= 12:
            blockers.append(f"invalid_horizon:{forecast.series_id}:{forecast.horizon}")
        if forecast.value < 0:
            blockers.append(f"negative_forecast:{forecast.series_id}:{forecast.engine}")
        if forecast.issued_at[:7] >= period[:7]:
            blockers.append(f"forecast_not_prior:{forecast.series_id}:{forecast.engine}")

    for series_id in seen:
        if not any(f.series_id == series_id and f.engine == "towell" and f.frozen for f in relevant):
            blockers.append(f"missing_frozen_towell:{series_id}")
        if not any(f.series_id == series_id and f.engine == "statistical" and f.frozen for f in relevant):
            warnings.append(f"missing_statistical_vintage:{series_id}")
        if not any(f.series_id == series_id and f.engine in ("ml", "challenger") and f.frozen for f in relevant):
            warnings.append(f"missing_ml_vintage:{series_id}")

    return ValidationResult(not blockers, tuple(sorted(set(blockers))), tuple(sorted(set(warnings))))


def _engine_metrics(records: list[ActualRecord], forecasts: list[FrozenForecast]) -> list[dict[str, Any]]:
    actual_by_series = {row.series_id: float(row.sale) for row in records if row.active and row.sale is not None}
    output: list[dict[str, Any]] = []
    for engine in ENGINES:
        rows = [f for f in forecasts if f.engine == engine and f.series_id in actual_by_series]
        if not rows:
            continue
        # For the monthly official comparison, the most recent frozen vintage (+1)
        # is preferred. If unavailable, use the smallest available horizon.
        selected: dict[str, FrozenForecast] = {}
        for row in sorted(rows, key=lambda item: item.horizon):
            selected.setdefault(row.series_id, row)
        actual = [actual_by_series[key] for key in sorted(selected)]
        predicted = [selected[key].value for key in sorted(selected)]
        output.append({
            "engine": engine,
            "wape": _round(_wape(actual, predicted)),
            "bias": _round(_bias(actual, predicted)),
            "bias_direction": "overforecast" if _bias(actual, predicted) > 0 else "underforecast" if _bias(actual, predicted) < 0 else "neutral",
            "observations": len(actual),
            "actual_total": _round(sum(actual)),
            "forecast_total": _round(sum(predicted)),
            "absolute_error": _round(sum(abs(a - f) for a, f in zip(actual, predicted))),
            "versions": sorted({row.version for row in selected.values()}),
        })
    return output


def _horizon_metrics(records: list[ActualRecord], forecasts: list[FrozenForecast]) -> list[dict[str, Any]]:
    actual_by_series = {row.series_id: float(row.sale) for row in records if row.active and row.sale is not None}
    output: list[dict[str, Any]] = []
    for engine in ENGINES:
        for horizon in range(1, 13):
            rows = [f for f in forecasts if f.engine == engine and f.horizon == horizon and f.series_id in actual_by_series]
            if not rows:
                continue
            actual = [actual_by_series[row.series_id] for row in rows]
            predicted = [row.value for row in rows]
            output.append({"engine": engine, "horizon": horizon, "wape": _round(_wape(actual, predicted)), "bias": _round(_bias(actual, predicted)), "observations": len(rows)})
    return output


def _interval_coverage(records: list[ActualRecord], forecasts: list[FrozenForecast]) -> list[dict[str, Any]]:
    actual_by_series = {row.series_id: float(row.sale) for row in records if row.active and row.sale is not None}
    output: list[dict[str, Any]] = []
    for horizon in range(1, 13):
        rows = [f for f in forecasts if f.engine == "towell" and f.horizon == horizon and f.series_id in actual_by_series and f.p90 is not None and f.p95 is not None]
        if not rows:
            continue
        evaluations = []
        for row in rows:
            actual = actual_by_series[row.series_id]
            lower = 0.0 if row.p10 is None else row.p10
            evaluations.append({
                "series_id": row.series_id,
                "actual": actual,
                "within_p90": lower <= actual <= float(row.p90),
                "within_p95": lower <= actual <= float(row.p95),
                "below_p10": row.p10 is not None and actual < row.p10,
                "at_or_below_p50": row.p50 is not None and actual <= row.p50,
                "outside_p95": actual < lower or actual > float(row.p95),
            })
        output.append({
            "horizon": horizon,
            "observations": len(evaluations),
            "coverage_p90": _round(mean(1.0 if row["within_p90"] else 0.0 for row in evaluations) * 100),
            "coverage_p95": _round(mean(1.0 if row["within_p95"] else 0.0 for row in evaluations) * 100),
            "below_p10": sum(1 for row in evaluations if row["below_p10"]),
            "at_or_below_p50": sum(1 for row in evaluations if row["at_or_below_p50"]),
            "outside_p95": sum(1 for row in evaluations if row["outside_p95"]),
            "evaluations": evaluations,
        })
    return output


def _rolling_metrics(current: list[dict[str, Any]], history: list[HistoricalMetric], period: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for metric in current:
        points = [row for row in history if row.engine == metric["engine"] and _period_key(row.period) < _period_key(period)]
        points.sort(key=lambda row: _period_key(row.period))
        all_points = points + [HistoricalMetric(period, metric["engine"], metric["wape"], metric["bias"], metric["observations"])]
        windows: dict[str, Any] = {}
        for size, label in ((1, "month"), (3, "last_3"), (6, "last_6"), (12, "last_12")):
            chosen = all_points[-size:]
            windows[label] = {"wape": _round(mean(row.wape for row in chosen)), "bias": _round(mean(row.bias for row in chosen)), "periods": len(chosen)}
        windows["all"] = {"wape": _round(mean(row.wape for row in all_points)), "bias": _round(mean(row.bias for row in all_points)), "periods": len(all_points)}
        output.append({"engine": metric["engine"], **windows})
    return output


def _persistent_bias(current: list[dict[str, Any]], history: list[HistoricalMetric], config: ClosureConfig) -> list[dict[str, Any]]:
    signals = []
    for metric in current:
        values = [row.bias for row in sorted((h for h in history if h.engine == metric["engine"]), key=lambda row: _period_key(row.period))]
        values.append(metric["bias"])
        recent = values[-config.persistent_bias_periods:]
        if len(recent) == config.persistent_bias_periods and (all(v > 0 for v in recent) or all(v < 0 for v in recent)):
            signals.append({"engine": metric["engine"], "direction": "overforecast" if recent[0] > 0 else "underforecast", "periods": len(recent), "biases": [_round(value) for value in recent]})
    return signals


def _challenger_validation(metrics: list[dict[str, Any]], horizon_metrics: list[dict[str, Any]], history: list[HistoricalMetric], config: ClosureConfig) -> dict[str, Any]:
    by_engine = {row["engine"]: row for row in metrics}
    champion = by_engine.get("statistical") or by_engine.get("towell")
    challenger = by_engine.get("challenger") or by_engine.get("ml")
    if not champion or not challenger:
        return {"state": "detected", "automatic_promotion": False, "reason": "insufficient_comparable_observations", "consecutive_wins": 0}

    champion_by_period: dict[str, HistoricalMetric] = {}
    challenger_by_period: dict[str, HistoricalMetric] = {}
    for row in history:
        if row.engine in ("statistical", "towell") and (row.period not in champion_by_period or row.engine == "statistical"):
            champion_by_period[row.period] = row
        if row.engine in ("challenger", "ml") and (row.period not in challenger_by_period or row.engine == "challenger"):
            challenger_by_period[row.period] = row
    common_periods = sorted(set(champion_by_period) & set(challenger_by_period), key=_period_key)[-12:]
    past = [(champion_by_period[p].wape, challenger_by_period[p].wape, challenger_by_period[p].bias) for p in common_periods]
    comparisons = past + [(champion["wape"], challenger["wape"], challenger["bias"])]
    minimum = config.minimum_improvement
    winning = [cl + minimum <= ch and abs(bias) <= config.maximum_absolute_bias for ch, cl, bias in comparisons]
    consecutive = 0
    for result in reversed(winning):
        if not result:
            break
        consecutive += 1

    recent_challenger = [item[1] for item in comparisons[-config.challenger_periods_required:]]
    stable = len(recent_challenger) >= config.challenger_periods_required and pstdev(recent_challenger) <= config.maximum_challenger_wape_stddev
    champion_h = {row["horizon"]: row["wape"] for row in horizon_metrics if row["engine"] in ("statistical", "towell")}
    challenger_h = {row["horizon"]: row["wape"] for row in horizon_metrics if row["engine"] in ("challenger", "ml")}
    critical_degradation = {h: _round(challenger_h[h] - champion_h[h]) for h in config.critical_horizons if h in champion_h and h in challenger_h and challenger_h[h] - champion_h[h] > config.maximum_critical_horizon_degradation}
    enough = consecutive >= config.challenger_periods_required and stable and not critical_degradation
    state = "candidate_for_promotion" if enough else "not_consistent" if len(comparisons) >= config.challenger_periods_required and consecutive == 0 else "in_validation"
    return {
        "state": state,
        "automatic_promotion": False,
        "champion": "statistical",
        "challenger": "ml_revalidated",
        "champion_reference_wape": config.champion_reference_wape,
        "challenger_reference_wape": config.challenger_reference_wape,
        "current_champion_wape": champion["wape"],
        "current_challenger_wape": challenger["wape"],
        "improvement_points": _round(champion["wape"] - challenger["wape"]),
        "consecutive_wins": consecutive,
        "required_consecutive_wins": config.challenger_periods_required,
        "stable": stable,
        "critical_horizon_degradation": critical_degradation,
        "evidence_sufficient": enough,
    }


def _drift(records: list[ActualRecord], prior_sales: dict[str, list[float]], config: ClosureConfig) -> list[dict[str, Any]]:
    signals = []
    for row in records:
        if not row.active or row.sale is None:
            continue
        history = [float(value) for value in prior_sales.get(row.series_id, []) if value is not None]
        if len(history) < 3:
            continue
        baseline = mean(history[-6:])
        relative = abs(float(row.sale) - baseline) / max(abs(baseline), 1.0)
        if relative >= config.drift_relative_change:
            signals.append({"series_id": row.series_id, "type": "distribution_shift", "severity": "significant" if relative >= config.drift_relative_change * 1.5 else "warning", "relative_change": _round(relative), "baseline": _round(baseline), "actual": row.sale})
    return signals


def _snapshot_hash(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(stable.encode("utf-8")).hexdigest()


def run_closure(
    period: str,
    records: list[ActualRecord],
    forecasts: list[FrozenForecast],
    history: list[HistoricalMetric] | None = None,
    prior_sales: dict[str, list[float]] | None = None,
    config: ClosureConfig | None = None,
    revision: int = 1,
    previous_snapshot_hash: str | None = None,
    correction_reason: str | None = None,
    actor: str = "system",
    closed_at: str | None = None,
) -> dict[str, Any]:
    config = config or ClosureConfig()
    history = history or []
    prior_sales = prior_sales or {}
    validation = validate_closure(records, forecasts, period)
    if not validation.valid:
        return {"status": "blocked", "period_state": "validation", "validation": asdict(validation), "champion_changed": False}
    if revision > 1 and (not previous_snapshot_hash or not correction_reason):
        return {"status": "blocked", "period_state": "validation", "validation": {"valid": False, "blockers": ["correction_requires_previous_snapshot_and_reason"], "warnings": []}, "champion_changed": False}

    active = [row for row in records if row.active and row.period[:7] == period[:7]]
    relevant_forecasts = [row for row in forecasts if row.target_period[:7] == period[:7]]
    metrics = _engine_metrics(active, relevant_forecasts)
    horizon = _horizon_metrics(active, relevant_forecasts)
    coverage = _interval_coverage(active, relevant_forecasts)
    rolling = _rolling_metrics(metrics, history, period)
    bias_signals = _persistent_bias(metrics, history, config)
    challenger = _challenger_validation(metrics, horizon, history, config)
    drift = _drift(active, prior_sales, config)
    totals = {
        "sale": _round(sum(float(row.sale) for row in active if row.sale is not None)),
        "order": _round(sum(float(row.order) for row in active if row.order is not None)),
        "delivery": _round(sum(float(row.delivery) for row in active if row.delivery is not None)),
    }
    service = {
        "fill_rate": _round(_ratio(totals["delivery"], totals["order"])),
        "sale_to_order": _round(_ratio(totals["sale"], totals["order"])),
        "order_zero_rule": "100_when_order_and_delivery_are_zero; undefined_when_order_is_zero_and_delivery_is_positive",
    }

    towell = next((row for row in metrics if row["engine"] == "towell"), None)
    towell_roll = next((row for row in rolling if row["engine"] == "towell"), None)
    retrain_reasons = []
    if towell and towell["wape"] - config.champion_reference_wape >= config.retrain_deterioration_points:
        retrain_reasons.append("sustained_wape_deterioration_candidate")
    if any(row["severity"] == "significant" for row in drift):
        retrain_reasons.append("significant_drift")
    if int(period[5:7]) % 2 == 0:
        retrain_reasons.append("bimonthly_review")
    learning_events = [
        {"type": "actuals_appended", "status": "ready", "series": len(active)},
        {"type": "next_cycle_prepared", "status": "ready", "period": period},
    ]
    if retrain_reasons:
        learning_events.append({"type": "retraining_requested", "status": "queued", "reasons": retrain_reasons, "publication_allowed": False})
    if int(period[5:7]) % 2 == 0:
        learning_events.append({"type": "bimonthly_review", "status": "queued", "scope": ["wape","bias","fill_rate","horizons","drift","champion","challenger","intervals","accuracy_trend","client_benchmark"]})
    if revision > 1:
        learning_events.append({"type": "closure_corrected", "status": "observed", "reason": correction_reason, "previous_snapshot_hash": previous_snapshot_hash})

    confidence = "low"
    if towell:
        p90_values = [row["coverage_p90"] for row in coverage]
        if towell["wape"] <= config.champion_reference_wape and (not p90_values or mean(p90_values) >= 75):
            confidence = "high"
        elif towell["wape"] <= config.champion_reference_wape + 10:
            confidence = "medium"

    comparison = {
        "client_wape": next((row["wape"] for row in metrics if row["engine"] == "client"), None),
        "towell_wape": towell["wape"] if towell else None,
    }
    comparison["towell_value_added_points"] = _round(comparison["client_wape"] - comparison["towell_wape"]) if comparison["client_wape"] is not None and comparison["towell_wape"] is not None else None

    identity = f"CLOSE-FENDI-{period[:7]}-R{revision:02d}"
    closed_at = closed_at or datetime.now(timezone.utc).isoformat()
    snapshot = {
        "closure_id": identity,
        "period": period[:7],
        "revision": revision,
        "closed_at": closed_at,
        "actor": actor,
        "source_contract": "normalized_platform_records",
        "realized": [asdict(row) for row in sorted(active, key=lambda row: row.series_id)],
        "frozen_forecasts": [asdict(row) for row in sorted(relevant_forecasts, key=lambda row: (row.engine, row.series_id, row.horizon))],
        "metrics": metrics,
        "service": service,
        "horizon_accuracy": horizon,
        "interval_coverage": coverage,
        "rolling_accuracy": rolling,
        "persistent_bias": bias_signals,
        "challenger_validation": challenger,
        "drift": drift,
        "benchmark": comparison,
        "confidence": confidence,
        "learning_events": learning_events,
        "model_state": {"champion": "statistical", "champion_changed": False, "challenger": "ml_revalidated", "challenger_state": challenger["state"]},
        "engine_version": ENGINE_VERSION,
        "previous_snapshot_hash": previous_snapshot_hash,
    }
    snapshot_hash = _snapshot_hash(snapshot)
    return {
        "status": "closed",
        "period_state": "closed",
        "closure_id": identity,
        "revision": revision,
        "validation": asdict(validation),
        "totals": totals,
        "metrics": metrics,
        "service": service,
        "horizon_accuracy": horizon,
        "interval_coverage": coverage,
        "rolling_accuracy": rolling,
        "persistent_bias": bias_signals,
        "challenger_validation": challenger,
        "drift": drift,
        "benchmark": comparison,
        "confidence": confidence,
        "learning_events": learning_events,
        "snapshot": snapshot,
        "snapshot_hash": snapshot_hash,
        "snapshot_immutable": True,
        "champion_changed": False,
        "forecast_towell_changed": False,
        "next_cycle_prepared": True,
        "towell_trend": towell_roll,
    }


def payload_from_dict(payload: dict[str, Any]) -> dict[str, Any]:
    records = [ActualRecord(**row) for row in payload["records"]]
    forecasts = [FrozenForecast(**row) for row in payload["forecasts"]]
    history = [HistoricalMetric(**row) for row in payload.get("history", [])]
    config_payload = payload.get("configuration", {})
    if "critical_horizons" in config_payload:
        config_payload["critical_horizons"] = tuple(config_payload["critical_horizons"])
    return run_closure(
        payload["period"], records, forecasts, history, payload.get("prior_sales", {}), ClosureConfig(**config_payload),
        int(payload.get("revision", 1)), payload.get("previous_snapshot_hash"), payload.get("correction_reason"), payload.get("actor", "system"), payload.get("closed_at"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a PRD 06 closure from normalized records")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = payload_from_dict(json.loads(args.input.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
