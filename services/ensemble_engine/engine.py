"""PRD 05 ensemble engine for the official FORECAST Towell output.

The engine consumes aligned, out-of-sample predictions from the statistical and ML
engines. It never reads Excel, never invents ML participation, and never replaces a
valid Champion automatically. A better result is recorded as a Challenger until an
authorized publication step promotes it.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.ml_engine import engine as ml_engine
from services.statistical_engine import engine as statistical_engine

ENGINE_VERSION = "prd05-1.0.0"
HORIZONS = tuple(range(1, 13))


@dataclass(frozen=True)
class EnsembleConfig:
    minimum_improvement: float = 0.25
    reference_champion_wape: float | None = 24.0
    bias_penalty: float = 0.18
    stability_penalty: float = 0.10
    deterioration_penalty: float = 0.12
    max_bias_deterioration: float = 5.0
    max_stability_deterioration: float = 10.0
    minimum_observations: int = 24
    minimum_windows: int = 3
    divergence_alert_threshold: float = 30.0
    coarse_step: float = 0.10
    fine_step: float = 0.025
    fine_radius: float = 0.10


@dataclass(frozen=True)
class BacktestRecord:
    series_id: str
    issue_period: str
    target_period: str
    horizon: int
    actual: float
    statistical: float
    ml: float | None


@dataclass(frozen=True)
class FutureRecord:
    series_id: str
    label: str
    period: str
    horizon: int
    statistical: float
    ml: float | None


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _metrics(actual: list[float], predicted: list[float], window_keys: list[str]) -> dict:
    errors = [a - p for a, p in zip(actual, predicted)]
    denominator = sum(actual)
    wape = 100 * sum(abs(error) for error in errors) / denominator if denominator else 0.0
    bias = 100 * sum(errors) / denominator if denominator else 0.0
    per_window = []
    for key in sorted(set(window_keys)):
        indexes = [index for index, value in enumerate(window_keys) if value == key]
        window_actual = [actual[index] for index in indexes]
        window_predicted = [predicted[index] for index in indexes]
        window_denominator = sum(window_actual)
        if window_denominator:
            per_window.append(100 * sum(abs(a - p) for a, p in zip(window_actual, window_predicted)) / window_denominator)
    stability = statistics.pstdev(per_window) if len(per_window) > 1 else 0.0
    split = max(1, len(per_window) * 2 // 3)
    historical = statistics.fmean(per_window[:split]) if per_window else wape
    recent = statistics.fmean(per_window[split:]) if per_window[split:] else historical
    return {
        "observations": len(actual),
        "windows": len(set(window_keys)),
        "wape": round(wape, 4),
        "bias": round(bias, 4),
        "stability": round(stability, 4),
        "recent_wape": round(recent, 4),
        "historical_wape": round(historical, 4),
        "deterioration": round(max(0.0, recent - historical), 4),
    }


def candidate_weights(config: EnsembleConfig) -> list[float]:
    coarse = [round(1.0 - index * config.coarse_step, 6) for index in range(round(1 / config.coarse_step) + 1)]
    return sorted(set(max(0.0, min(1.0, value)) for value in coarse), reverse=True)


def _prediction(record: BacktestRecord, statistical_weight: float) -> float | None:
    if record.ml is None:
        return record.statistical if math.isclose(statistical_weight, 1.0) else None
    return max(0.0, record.statistical * statistical_weight + record.ml * (1.0 - statistical_weight))


def evaluate_candidate(records: list[BacktestRecord], statistical_weight: float, config: EnsembleConfig) -> dict | None:
    usable = [(record, _prediction(record, statistical_weight)) for record in records]
    usable = [(record, value) for record, value in usable if value is not None]
    if not usable:
        return None
    actual = [record.actual for record, _ in usable]
    predicted = [float(value) for _, value in usable]
    windows = [record.target_period for record, _ in usable]
    aggregate = _metrics(actual, predicted, windows)
    score = (
        aggregate["wape"]
        + abs(aggregate["bias"]) * config.bias_penalty
        + aggregate["stability"] * config.stability_penalty
        + aggregate["deterioration"] * config.deterioration_penalty
    )
    by_horizon = []
    for horizon in HORIZONS:
        subset = [(record, value) for record, value in usable if record.horizon == horizon]
        if subset:
            by_horizon.append({"horizon": horizon, **_metrics(
                [record.actual for record, _ in subset],
                [float(value) for _, value in subset],
                [record.target_period for record, _ in subset],
            )})
    by_series = []
    for series_id in sorted({record.series_id for record, _ in usable}):
        subset = [(record, value) for record, value in usable if record.series_id == series_id]
        if len(subset) >= 6:
            by_series.append({"series_id": series_id, **_metrics(
                [record.actual for record, _ in subset],
                [float(value) for _, value in subset],
                [record.target_period for record, _ in subset],
            )})
    strategy = "statistical" if math.isclose(statistical_weight, 1.0) else "ml" if math.isclose(statistical_weight, 0.0) else "ensemble"
    return {
        "strategy": strategy,
        "statistical_weight": round(statistical_weight, 4),
        "ml_weight": round(1.0 - statistical_weight, 4),
        "score": round(score, 4),
        **aggregate,
        "by_horizon": by_horizon,
        "by_series": by_series,
    }


def search_candidates(records: list[BacktestRecord], config: EnsembleConfig) -> list[dict]:
    coarse = [row for weight in candidate_weights(config) if (row := evaluate_candidate(records, weight, config))]
    if not coarse:
        return []
    best = min(coarse, key=lambda row: row["score"])
    center = best["statistical_weight"]
    steps = round(config.fine_radius / config.fine_step)
    fine_weights = [round(center + offset * config.fine_step, 6) for offset in range(-steps, steps + 1)]
    all_weights = set(candidate_weights(config)) | {max(0.0, min(1.0, value)) for value in fine_weights}
    candidates = [row for weight in sorted(all_weights, reverse=True) if (row := evaluate_candidate(records, weight, config))]
    return sorted(candidates, key=lambda row: (row["score"], row["wape"], -row["statistical_weight"]))


def _confidence(candidate: dict, divergence: float, observations: int) -> str:
    points = 0
    points += 2 if candidate["wape"] <= 20 else 1 if candidate["wape"] <= 35 else 0
    points += 2 if candidate["stability"] <= 8 else 1 if candidate["stability"] <= 18 else 0
    points += 2 if divergence <= 15 else 1 if divergence <= 30 else 0
    points += 2 if observations >= 120 else 1 if observations >= 48 else 0
    return "Alta" if points >= 7 else "Media" if points >= 4 else "Baja"


def _bands(value: float, residuals: list[float], horizon: int) -> dict:
    if not residuals:
        residuals = [0.0]
    scale = math.sqrt(max(1, horizon)) if len(residuals) < 5 else 1.0
    p10 = min(value, max(0.0, value + _quantile(residuals, 0.10) * scale))
    p90 = max(value, value + _quantile(residuals, 0.90) * scale)
    p95 = max(p90, value + _quantile(residuals, 0.95) * scale)
    return {"p10": round(p10, 4), "p50": round(value, 4), "p90": round(p90, 4), "p95": round(p95, 4), "residual_count": len(residuals)}


def select_strategy(records: list[BacktestRecord], config: EnsembleConfig, incumbent_strategy: str = "statistical") -> dict:
    candidates = search_candidates(records, config)
    if not candidates:
        return {"status": "insufficient", "reason": "No existen predicciones alineadas suficientes.", "candidates": []}
    statistical = next((row for row in candidates if row["strategy"] == "statistical"), None)
    machine_learning = next((row for row in candidates if row["strategy"] == "ml"), None)
    available_individuals = [row for row in (statistical, machine_learning) if row]
    incumbent = next((row for row in available_individuals if row["strategy"] == incumbent_strategy), None)
    incumbent = incumbent or min(available_individuals, key=lambda row: row["wape"])
    best = candidates[0]
    benchmark_wape = min(incumbent["wape"], config.reference_champion_wape if config.reference_champion_wape is not None else incumbent["wape"])
    improvement = benchmark_wape - best["wape"]
    enough_evidence = best["observations"] >= config.minimum_observations and best["windows"] >= config.minimum_windows
    controlled = (
        abs(best["bias"]) <= abs(incumbent["bias"]) + config.max_bias_deterioration
        and best["stability"] <= incumbent["stability"] + config.max_stability_deterioration
        and best["score"] < incumbent["score"]
    )
    eligible = best["strategy"] != incumbent["strategy"] and improvement >= config.minimum_improvement and enough_evidence and controlled
    for candidate in candidates:
        candidate["no_degradation_pass"] = candidate is incumbent or candidate["wape"] <= benchmark_wape
        candidate["minimum_improvement_pass"] = benchmark_wape - candidate["wape"] >= config.minimum_improvement
        candidate["state"] = "challenger" if eligible and candidate is best else "champion" if candidate is incumbent else "rejected"
        if candidate["state"] == "rejected":
            candidate["rejection_reason"] = "no_degradation" if not candidate["no_degradation_pass"] else "minimum_improvement_or_controls"
    return {
        "status": "challenger" if eligible else "champion",
        "incumbent": incumbent,
        "challenger": best if eligible else None,
        "official": incumbent,
        "improvement_points": round(max(0.0, improvement), 4),
        "reference_champion_wape": round(benchmark_wape, 4),
        "minimum_improvement": config.minimum_improvement,
        "candidates": candidates,
        "decision": "challenger_requires_authorized_validation" if eligible else "champion_preserved_by_no_degradation",
    }


def build_forecast(records: list[BacktestRecord], future: list[FutureRecord], official: dict, config: EnsembleConfig) -> tuple[list[dict], list[dict]]:
    forecasts, alerts = [], []
    weight = official["statistical_weight"]
    for row in future:
        if row.ml is None or math.isclose(weight, 1.0):
            raw = row.statistical
            applied_weight = 1.0
        else:
            raw = row.statistical * weight + row.ml * (1.0 - weight)
            applied_weight = weight
        adjusted = max(0.0, raw)
        if raw < 0:
            alerts.append({"type": "negative_clamp", "severity": "info", "series_id": row.series_id, "period": row.period, "raw_value": raw})
        comparable = [item for item in records if item.series_id == row.series_id and item.horizon == row.horizon]
        if not comparable:
            comparable = [item for item in records if item.horizon == row.horizon]
        residuals = [item.actual - float(_prediction(item, applied_weight) or 0.0) for item in comparable]
        divergence = 0.0 if row.ml is None else 100 * abs(row.statistical - row.ml) / max(abs(row.statistical), 1.0)
        bands = _bands(adjusted, residuals, row.horizon)
        confidence = _confidence(official, divergence, len(comparable))
        if divergence >= config.divergence_alert_threshold:
            alerts.append({"type": "high_divergence", "severity": "warning", "series_id": row.series_id, "period": row.period, "divergence": round(divergence, 4)})
        forecasts.append({
            "series_id": row.series_id,
            "label": row.label,
            "period": row.period,
            "horizon": row.horizon,
            "statistical": round(row.statistical, 4),
            "ml": None if row.ml is None else round(row.ml, 4),
            "statistical_weight": round(applied_weight, 4),
            "ml_weight": round(1.0 - applied_weight, 4),
            "raw_value": round(raw, 4),
            "value": round(adjusted, 4),
            "operational_value": round(adjusted),
            "divergence": round(divergence, 4),
            "confidence": confidence,
            "probability": bands,
        })
    return forecasts, alerts


def run_ensemble(records: list[BacktestRecord], future: list[FutureRecord], cutoff: str, statistical_version: str, ml_version: str | None, config: EnsembleConfig | None = None, target: str = "Venta", published_statistical_wape: float | None = None, published_ml_wape: float | None = None, promote_challenger: bool = False) -> dict:
    config = config or EnsembleConfig()
    selection = select_strategy(records, config)
    if selection["status"] == "insufficient":
        return {**selection, "engine_version": ENGINE_VERSION, "fallback": "last_valid_forecast"}
    authorized_promotion = bool(promote_challenger and selection.get("challenger"))
    if authorized_promotion:
        previous = selection["official"]
        promoted = selection["challenger"]
        selection["official"] = promoted
        selection["status"] = "champion"
        selection["decision"] = "challenger_promoted_by_authorized_user"
        selection["promoted_from"] = previous["strategy"]
        for candidate in selection["candidates"]:
            if candidate is promoted:
                candidate["state"] = "champion"
            elif candidate is previous:
                candidate["state"] = "retired_champion"
    forecasts, alerts = build_forecast(records, future, selection["official"], config)
    version = f"FT-FENDI-{cutoff.replace('-', '')}-V01"
    return {
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "version": version,
        "cutoff": cutoff,
        "target": target,
        "source": "normalized_platform_records",
        "excel_required": False,
        "statistical_version": statistical_version,
        "ml_version": ml_version,
        "published_metrics": {"statistical_wape": published_statistical_wape, "ml_wape": published_ml_wape},
        "client_forecast_role": "external_benchmark_only",
        "selection": selection,
        "forecast_towell": forecasts,
        "alerts": alerts,
        "fallback_order": ["champion_forecast_towell", "champion_statistical", "last_valid_published_forecast"],
        "publication": {"automatic_promotion": False, "authorized_promotion": authorized_promotion, "official_state": "champion", "challenger_state": None if authorized_promotion else "pending_validation" if selection["challenger"] else None},
        "configuration": asdict(config),
    }


def load_normalized_series(path: Path) -> list[ml_engine.Series]:
    grouped: dict[str, ml_engine.Series] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["objective"].lower() != "venta":
                continue
            series_id = row["canonical_product_id"]
            label = row["description"].replace("TOALLA MB FENDI ", "").title()
            series = grouped.setdefault(series_id, ml_engine.Series(series_id, label, label, "Fendi", {}))
            series.points[row["period"]] = None if row["is_missing"].lower() == "true" or not row["value"].strip() else float(row["value"])
    return list(grouped.values())


def build_common_backtest_records(all_series: list[ml_engine.Series], statistical_models: dict[str, str], ml_factory: Callable[[], object] | None, origins_per_horizon: int = 3) -> list[BacktestRecord]:
    """Rebuild aligned folds; every feature and model sees data available at issue time only."""
    periods = sorted({period for series in all_series for period in series.points})
    records: list[BacktestRecord] = []
    for horizon in HORIZONS:
        samples, _, _ = ml_engine.build_samples(all_series, horizon)
        target_periods = sorted({sample.target_period for sample in samples})
        valid_targets = []
        for target in target_periods:
            train = [sample for sample in samples if sample.target_period < target]
            test = [sample for sample in samples if sample.target_period == target]
            if len(train) >= 18 and test:
                valid_targets.append(target)
        for target in valid_targets[-origins_per_horizon:]:
            train = [sample for sample in samples if sample.target_period < target]
            test = [sample for sample in samples if sample.target_period == target]
            ml_predictions: dict[str, float] = {}
            if ml_factory is not None:
                try:
                    prep = ml_engine.Preprocessor().fit([sample.features for sample in train])
                    model = ml_factory().fit(prep.transform([sample.features for sample in train]), ml_engine.np.array([sample.target for sample in train]))
                    predicted = model.predict(prep.transform([sample.features for sample in test]))
                    ml_predictions = {sample.series_id: float(value) for sample, value in zip(test, predicted)}
                except Exception:
                    ml_predictions = {}
            target_index = periods.index(target)
            issue_index = target_index - horizon
            if issue_index < 0:
                continue
            product_rows = []
            for sample in test:
                series = next(item for item in all_series if item.id == sample.series_id)
                history = [series.points.get(period) for period in periods[:issue_index + 1]]
                observed = [float(value) for value in history if value is not None]
                if not observed:
                    continue
                model_name = statistical_models.get(series.id, "Naive")
                model_function = statistical_engine.MODELS.get(model_name, statistical_engine.naive)
                try:
                    statistical = statistical_engine.clamp(model_function(observed, horizon))[-1]
                except ValueError:
                    statistical = observed[-1]
                record = BacktestRecord(series.id, periods[issue_index], target, horizon, float(sample.target), float(statistical), ml_predictions.get(series.id))
                records.append(record)
                product_rows.append(record)
            if product_rows:
                total_actual = sum(row.actual for row in product_rows)
                total_ml = sum(row.ml for row in product_rows if row.ml is not None) if all(row.ml is not None for row in product_rows) else None
                total_history = [sum(float(series.points.get(period) or 0.0) for series in all_series) for period in periods[:issue_index + 1]]
                total_model_name = statistical_models.get("total-fendi-bd", "Naive")
                total_function = statistical_engine.MODELS.get(total_model_name, statistical_engine.naive)
                try:
                    total_statistical = statistical_engine.clamp(total_function(total_history, horizon))[-1]
                except ValueError:
                    total_statistical = total_history[-1]
                records.append(BacktestRecord("total-fendi-bd", periods[issue_index], target, horizon, total_actual, total_statistical, total_ml))
    return records


def load_future(statistical_path: Path, ml_path: Path | None) -> tuple[list[FutureRecord], dict[str, str], str, str | None, str, float | None, float | None]:
    statistical_payload = json.loads(statistical_path.read_text(encoding="utf-8"))
    ml_payload = json.loads(ml_path.read_text(encoding="utf-8")) if ml_path else None
    ml_by_series = {row["series_id"]: row for row in ml_payload.get("forecast", [])} if ml_payload else {}
    future, models = [], {}
    for row in statistical_payload["series"]:
        if row.get("target") != "Venta" or not row.get("forecast"):
            continue
        models[row["series_id"]] = row.get("winner", "Naive")
        ml_row = ml_by_series.get(row["series_id"], {})
        for horizon, point in enumerate(row["forecast"], 1):
            ml_point = next((item for item in ml_row.get("forecast", []) if item["period"] == point["period"]), None)
            future.append(FutureRecord(row["series_id"], row["label"], point["period"], horizon, float(point["forecast"]), float(ml_point["value"]) if ml_point else None))
    statistical_total = next((row for row in statistical_payload["series"] if row.get("series_id") == "total-fendi-bd" and row.get("target") == "Venta"), {})
    return future, models, statistical_payload["run"]["version"], ml_payload.get("champion", {}).get("version") if ml_payload else None, statistical_payload["run"]["cutoff"], statistical_total.get("wape"), ml_payload.get("champion", {}).get("wape") if ml_payload else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--statistical", type=Path, required=True)
    parser.add_argument("--ml", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--promote-challenger", action="store_true", help="Publish an eligible Challenger after explicit user authorization.")
    parser.add_argument("--series-id", help="Evaluate and publish one grain-aligned series, for example total-fendi-bd.")
    args = parser.parse_args()
    future, models, statistical_version, ml_version, cutoff, statistical_wape, ml_wape = load_future(args.statistical, args.ml)
    series = load_normalized_series(args.input)
    factory = ml_engine.RandomForestGlobal if args.ml else None
    records = build_common_backtest_records(series, models, factory)
    if args.series_id:
        records = [row for row in records if row.series_id == args.series_id]
        future = [row for row in future if row.series_id == args.series_id]
    config = EnsembleConfig(reference_champion_wape=float(statistical_wape) if statistical_wape is not None else 24.0)
    payload = run_ensemble(records, future, cutoff, statistical_version, ml_version, config, "Venta", statistical_wape, ml_wape, args.promote_challenger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
