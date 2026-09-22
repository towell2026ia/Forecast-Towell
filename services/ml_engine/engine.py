"""Global Machine Learning engine for FORECAST Towell PRD 04.

This portable implementation uses only NumPy. It trains one global model across all
product series, preserves nulls as missing (never as zero), and evaluates every model
with temporal backtesting before producing a 12-month direct forecast.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import warnings
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

ENGINE_VERSION = "prd04-1.0.0"
HORIZONS = tuple(range(1, 13))


def add_month(period: str, offset: int) -> str:
    year, month = map(int, period.split("-"))
    index = year * 12 + month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def period_index(period: str) -> int:
    year, month = map(int, period.split("-"))
    return year * 12 + month - 1


@dataclass
class Series:
    id: str
    label: str
    color: str
    category: str
    points: dict[str, float | None]


@dataclass
class Sample:
    features: list[float | None]
    target: float
    target_period: str
    issue_period: str
    horizon: int
    series_id: str


class Preprocessor:
    def fit(self, rows: list[list[float | None]]) -> "Preprocessor":
        matrix = np.array([[np.nan if value is None else value for value in row] for row in rows], dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            self.median = np.nanmedian(matrix, axis=0)
        self.median = np.where(np.isnan(self.median), 0.0, self.median)
        filled = np.where(np.isnan(matrix), self.median, matrix)
        self.mean = filled.mean(axis=0)
        self.std = filled.std(axis=0)
        self.std = np.where(self.std < 1e-9, 1.0, self.std)
        return self

    def transform(self, rows: list[list[float | None]]) -> np.ndarray:
        matrix = np.array([[np.nan if value is None else value for value in row] for row in rows], dtype=float)
        missing = np.isnan(matrix).astype(float)
        filled = np.where(np.isnan(matrix), self.median, matrix)
        return np.concatenate(((filled - self.mean) / self.std, missing), axis=1)


class LinearGlobal:
    name = "Regresión Lineal Global"
    complexity = 0.0

    def fit(self, x: np.ndarray, y: np.ndarray) -> "LinearGlobal":
        design = np.column_stack((np.ones(len(x)), x))
        penalty = np.eye(design.shape[1]) * 0.35
        penalty[0, 0] = 0
        self.coef = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
        raw = np.abs(self.coef[1:])
        self.importance = raw / raw.sum() if raw.sum() else raw
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.maximum(0, np.column_stack((np.ones(len(x)), x)) @ self.coef)


@dataclass
class Node:
    value: float
    feature: int | None = None
    threshold: float | None = None
    left: "Node | None" = None
    right: "Node | None" = None


def fit_tree(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, depth: int = 0, max_depth: int = 4, min_leaf: int = 5, feature_fraction: float = 0.65, importance: np.ndarray | None = None) -> Node:
    node = Node(float(y.mean()))
    if depth >= max_depth or len(y) < min_leaf * 2 or np.var(y) < 1e-9:
        return node
    candidates = rng.choice(x.shape[1], max(1, int(x.shape[1] * feature_fraction)), replace=False)
    best = None
    parent_loss = float(np.sum((y - y.mean()) ** 2))
    for feature in candidates:
        values = x[:, feature]
        for threshold in np.unique(np.quantile(values, [0.33, 0.66])):
            mask = values <= threshold
            if mask.sum() < min_leaf or (~mask).sum() < min_leaf:
                continue
            loss = float(np.sum((y[mask] - y[mask].mean()) ** 2) + np.sum((y[~mask] - y[~mask].mean()) ** 2))
            if best is None or loss < best[0]:
                best = (loss, int(feature), float(threshold), mask)
    if best is None:
        return node
    loss, feature, threshold, mask = best
    node.feature, node.threshold = feature, threshold
    if importance is not None:
        importance[feature] += max(0, parent_loss - loss)
    node.left = fit_tree(x[mask], y[mask], rng, depth + 1, max_depth, min_leaf, feature_fraction, importance)
    node.right = fit_tree(x[~mask], y[~mask], rng, depth + 1, max_depth, min_leaf, feature_fraction, importance)
    return node


def predict_tree(node: Node, row: np.ndarray) -> float:
    while node.feature is not None and node.left is not None and node.right is not None:
        node = node.left if row[node.feature] <= node.threshold else node.right
    return node.value


class RandomForestGlobal:
    name = "Random Forest Global"
    complexity = 0.25

    def __init__(self, trees: int = 12, seed: int = 20260919):
        self.trees_count, self.seed = trees, seed

    def fit(self, x: np.ndarray, y: np.ndarray) -> "RandomForestGlobal":
        rng = np.random.default_rng(self.seed)
        self.trees, raw = [], np.zeros(x.shape[1])
        for _ in range(self.trees_count):
            indexes = rng.integers(0, len(y), len(y))
            self.trees.append(fit_tree(x[indexes], y[indexes], rng, max_depth=3, min_leaf=5, feature_fraction=.45, importance=raw))
        self.importance = raw / raw.sum() if raw.sum() else raw
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        predictions = np.array([[predict_tree(tree, row) for tree in self.trees] for row in x])
        return np.maximum(0, predictions.mean(axis=1))


class GradientBoostingGlobal:
    name = "Gradient Boosting Global"
    complexity = 0.35

    def __init__(self, rounds: int = 16, learning_rate: float = 0.12, seed: int = 20260919):
        self.rounds, self.learning_rate, self.seed = rounds, learning_rate, seed

    def fit(self, x: np.ndarray, y: np.ndarray) -> "GradientBoostingGlobal":
        rng = np.random.default_rng(self.seed)
        self.base = float(y.mean())
        prediction = np.full(len(y), self.base)
        self.trees, raw = [], np.zeros(x.shape[1])
        for _ in range(self.rounds):
            residual = y - prediction
            tree = fit_tree(x, residual, rng, max_depth=1, min_leaf=7, feature_fraction=0.55, importance=raw)
            self.trees.append(tree)
            prediction += self.learning_rate * np.array([predict_tree(tree, row) for row in x])
        self.importance = raw / raw.sum() if raw.sum() else raw
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        result = np.full(len(x), self.base)
        for tree in self.trees:
            result += self.learning_rate * np.array([predict_tree(tree, row) for row in x])
        return np.maximum(0, result)


MODEL_FACTORIES: dict[str, Callable[[], object]] = {
    LinearGlobal.name: LinearGlobal,
    RandomForestGlobal.name: RandomForestGlobal,
    GradientBoostingGlobal.name: GradientBoostingGlobal,
}


def load_series(path: Path, objective: str = "Venta") -> list[Series]:
    grouped: dict[str, Series] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["objective"].lower() != objective.lower():
                continue
            series_id = row["canonical_product_id"]
            label = row["description"].replace("TOALLA MB FENDI ", "").title()
            current = grouped.setdefault(series_id, Series(series_id, label, label, "Fendi", {}))
            current.points[row["period"]] = None if row["is_missing"].lower() == "true" or not row["value"].strip() else float(row["value"])
    return list(grouped.values())


def safe_mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def feature_vector(series: Series, periods: list[str], issue_index: int, target_period: str, horizon: int, series_ids: list[str], objective: str = "Venta") -> tuple[list[float | None], list[str]]:
    history = [series.points.get(period) for period in periods[:issue_index + 1]]
    observed = [value for value in history if value is not None]
    target_year, target_month = map(int, target_period.split("-"))
    names = ["año objetivo","mes objetivo","trimestre","seno mes","coseno mes","posición temporal","horizonte","antigüedad serie"]
    values: list[float | None] = [target_year, target_month, (target_month - 1) // 3 + 1, math.sin(2 * math.pi * target_month / 12), math.cos(2 * math.pi * target_month / 12), issue_index, horizon, len(observed)]
    for lag in (1, 2, 3, 6, 12):
        names.append(f"{objective.lower()} t-{lag}")
        index = len(history) - lag
        values.append(history[index] if index >= 0 else None)
    for window in (3, 6, 12):
        recent = [value for value in history[-window:] if value is not None]
        names.extend((f"promedio móvil {window}", f"desviación {window}", f"mínimo {window}", f"máximo {window}"))
        values.extend((safe_mean(recent), statistics.pstdev(recent) if len(recent) > 1 else 0.0 if recent else None, min(recent) if recent else None, max(recent) if recent else None))
    lag1 = history[-1] if history else None
    lag2 = history[-2] if len(history) > 1 else None
    lag12 = history[-12] if len(history) >= 12 else None
    mom = (lag1 / lag2 - 1) if lag1 is not None and lag2 not in (None, 0) else None
    yoy = (lag1 / lag12 - 1) if lag1 is not None and lag12 not in (None, 0) else None
    last3 = [value for value in history[-3:] if value is not None]
    prior3 = [value for value in history[-6:-3] if value is not None]
    slope = (last3[-1] - last3[0]) / max(1, len(last3) - 1) if len(last3) > 1 else None
    prior_slope = (prior3[-1] - prior3[0]) / max(1, len(prior3) - 1) if len(prior3) > 1 else None
    names.extend(("crecimiento mes contra mes","crecimiento anual","pendiente reciente","aceleración"))
    values.extend((mom, yoy, slope, slope - prior_slope if slope is not None and prior_slope is not None else None))
    nonzero_indexes = [index for index, value in enumerate(history) if value is not None and value > 0]
    months_since = len(history) - 1 - nonzero_indexes[-1] if nonzero_indexes else len(history)
    zero_count = sum(value == 0 for value in history if value is not None)
    movement = len(nonzero_indexes) / len(observed) if observed else 0
    intervals = [b - a for a, b in zip(nonzero_indexes, nonzero_indexes[1:])]
    last_event = "última venta" if objective.lower() == "venta" else "último pedido"
    names.extend((f"meses desde {last_event}","meses con demanda cero","porcentaje con movimiento","intervalo promedio"))
    values.extend((months_since, zero_count, movement, safe_mean(intervals)))
    names.extend(f"producto:{series_id}" for series_id in series_ids)
    values.extend(1.0 if series.id == series_id else 0.0 for series_id in series_ids)
    return values, names


def build_samples(all_series: list[Series], horizon: int, objective: str = "Venta") -> tuple[list[Sample], list[str], list[str]]:
    periods = sorted({period for series in all_series for period in series.points})
    ids = sorted(series.id for series in all_series)
    samples, feature_names = [], []
    for series in all_series:
        for issue_index in range(1, len(periods) - horizon):
            target_index = issue_index + horizon
            target_period = periods[target_index]
            target = series.points.get(target_period)
            if target is None:
                continue
            features, feature_names = feature_vector(series, periods, issue_index, target_period, horizon, ids, objective)
            samples.append(Sample(features, target, target_period, periods[issue_index], horizon, series.id))
    return samples, feature_names, periods


def metric(actual: list[float], predicted: list[float]) -> dict[str, float]:
    a, p = np.array(actual), np.array(predicted)
    error = a - p
    denominator = float(a.sum())
    return {
        "wape": round(100 * float(np.abs(error).sum()) / denominator, 2) if denominator else 0.0,
        "bias": round(100 * float(error.sum()) / denominator, 2) if denominator else 0.0,
        "mae": round(float(np.abs(error).mean()), 2),
        "rmse": round(float(np.sqrt(np.mean(error ** 2))), 2),
        "stability": round(100 * float(np.std(np.abs(error))) / (float(a.mean()) or 1), 2),
    }


def temporal_backtest(all_series: list[Series], factory: Callable[[], object], objective: str = "Venta") -> dict:
    horizon_results, actual_all, predicted_all = [], [], []
    for horizon in HORIZONS:
        samples, feature_names, _ = build_samples(all_series, horizon, objective)
        target_periods = sorted({sample.target_period for sample in samples})
        origins = target_periods[-min(2, max(0, len(target_periods) - 4)):]
        actual, predicted = [], []
        for origin in origins:
            train = [sample for sample in samples if sample.target_period < origin]
            test = [sample for sample in samples if sample.target_period == origin]
            if len(train) < 18 or not test:
                continue
            prep = Preprocessor().fit([sample.features for sample in train])
            model = factory().fit(prep.transform([sample.features for sample in train]), np.array([sample.target for sample in train]))
            pred = model.predict(prep.transform([sample.features for sample in test]))
            actual.extend(sample.target for sample in test)
            predicted.extend(map(float, pred))
        if actual:
            result = metric(actual, predicted)
            horizon_results.append({"horizon": horizon, "observations": len(actual), **result})
            actual_all.extend(actual); predicted_all.extend(predicted)
    if not actual_all:
        raise ValueError("No hay suficientes ventanas temporales")
    return {**metric(actual_all, predicted_all), "by_horizon": horizon_results, "feature_names": feature_names}


def rolling_backtest_history(all_series: list[Series], factory: Callable[[], object], objective: str = "Venta", max_origins: int = 12) -> list[dict]:
    """Build leak-free one-month-ahead predictions for Real vs Forecast views."""
    samples, _, _ = build_samples(all_series, 1, objective)
    target_periods = sorted({sample.target_period for sample in samples})
    valid_origins = []
    for origin in target_periods:
        train = [sample for sample in samples if sample.target_period < origin]
        test = [sample for sample in samples if sample.target_period == origin]
        if len(train) >= 18 and test:
            valid_origins.append(origin)
    rows: list[dict] = []
    for origin in valid_origins[-max_origins:]:
        train = [sample for sample in samples if sample.target_period < origin]
        test = [sample for sample in samples if sample.target_period == origin]
        prep = Preprocessor().fit([sample.features for sample in train])
        model = factory().fit(prep.transform([sample.features for sample in train]), np.array([sample.target for sample in train]))
        predicted = model.predict(prep.transform([sample.features for sample in test]))
        for sample, value in zip(test, predicted):
            rows.append({"series_id": sample.series_id, "period": origin, "actual": round(float(sample.target), 2), "forecast": round(float(value), 2)})
        rows.append({
            "series_id": "total-fendi-bd",
            "period": origin,
            "actual": round(sum(float(sample.target) for sample in test), 2),
            "forecast": round(sum(float(value) for value in predicted), 2),
        })
    return rows


def fit_forecast(all_series: list[Series], factory: Callable[[], object], objective: str = "Venta") -> tuple[list[dict], list[dict]]:
    periods = sorted({period for series in all_series for period in series.points})
    ids = sorted(series.id for series in all_series)
    results = {series.id: {"series_id": series.id, "label": series.label, "evidence": "low" if sum(v is not None for v in series.points.values()) < 12 else "standard", "forecast": []} for series in all_series}
    importance_rows = []
    for horizon in HORIZONS:
        samples, names, _ = build_samples(all_series, horizon, objective)
        prep = Preprocessor().fit([sample.features for sample in samples])
        model = factory().fit(prep.transform([sample.features for sample in samples]), np.array([sample.target for sample in samples]))
        features = [feature_vector(series, periods, len(periods) - 1, add_month(periods[-1], horizon), horizon, ids, objective)[0] for series in all_series]
        prediction = model.predict(prep.transform(features))
        for series, value in zip(all_series, prediction):
            results[series.id]["forecast"].append({"period": add_month(periods[-1], horizon), "horizon": horizon, "value": round(float(value), 2)})
        if horizon == 1:
            raw = getattr(model, "importance", np.zeros(len(names) * 2))[:len(names)]
            ranked = sorted(zip(names, map(float, raw)), key=lambda pair: pair[1], reverse=True)[:8]
            total = sum(value for _, value in ranked) or 1
            importance_rows = [{"feature": name, "importance": round(100 * value / total, 1)} for name, value in ranked]
    series_rows = list(results.values())
    total = []
    for horizon in HORIZONS:
        total.append({"period": add_month(periods[-1], horizon), "horizon": horizon, "value": round(sum(row["forecast"][horizon - 1]["value"] for row in series_rows), 2)})
    series_rows.insert(0, {"series_id": "total-fendi-bd", "label": "Total FENDI BD", "evidence": "global", "forecast": total})
    return series_rows, importance_rows


def drift(all_series: list[Series]) -> dict:
    periods = sorted({period for series in all_series for period in series.points})
    totals = [sum(series.points.get(period) or 0 for series in all_series if series.points.get(period) is not None) for period in periods]
    recent, baseline = totals[-3:], totals[-12:-3]
    if not recent or not baseline:
        return {"score": 0, "status": "insufficient"}
    score = abs(statistics.fmean(recent) - statistics.fmean(baseline)) / (statistics.pstdev(baseline) or 1)
    return {"score": round(score, 2), "status": "alert" if score >= 2 else "stable"}


def build_payload_from_series(all_series: list[Series], objective: str = "Venta") -> dict:
    if not all_series:
        return {"target": objective, "status": "insufficient", "reason": f"No existen observaciones normalizadas para {objective}."}
    candidates = []
    for name, factory in MODEL_FACTORIES.items():
        evaluation = temporal_backtest(all_series, factory, objective)
        complexity = factory().complexity
        score = evaluation["wape"] + abs(evaluation["bias"]) * 0.18 + evaluation["stability"] * 0.1 + complexity
        candidates.append({"model": name, "available": True, "score": round(score, 2), **evaluation})
    candidates.extend([
        {"model": "XGBoost Global", "available": False, "reason": "Dependencia opcional no habilitada en el runtime portátil."},
        {"model": "LightGBM Global", "available": False, "reason": "Dependencia opcional no habilitada en el runtime portátil."},
    ])
    available = sorted([row for row in candidates if row["available"]], key=lambda row: row["score"])
    winner, challenger = available[0], available[1]
    forecast, importance = fit_forecast(all_series, MODEL_FACTORIES[winner["model"]], objective)
    backtest_history = rolling_backtest_history(all_series, MODEL_FACTORIES[winner["model"]], objective)
    drift_result = drift(all_series)
    alerts = []
    if drift_result["status"] == "alert": alerts.append({"type": "drift", "severity": "warning", "message": "Posible cambio de patrón en los últimos tres periodos."})
    if any(row["evidence"] == "low" for row in forecast): alerts.append({"type": "low_evidence", "severity": "info", "message": "Tres productos dependen principalmente de patrones globales por contar con menos de 12 meses."})
    return {
        "target": objective, "status": "completed_with_alerts" if alerts else "completed", "engine_version": ENGINE_VERSION,
        "cutoff": max(period for series in all_series for period, value in series.points.items() if value is not None),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "dataset": {"series": len(all_series), "observations": sum(value is not None for series in all_series for value in series.points.values()), "source": "platform_normalized_records", "excel_required": False},
        "champion": {"version": f"ML-FENDI-{date.today().strftime('%Y%m%d')}-01", "status": "Champion", **winner},
        "challenger": {"version": f"ML-FENDI-{date.today().strftime('%Y%m%d')}-02", "status": "Challenger", **challenger},
        "candidates": candidates, "forecast": forecast, "backtest": backtest_history, "feature_importance": importance, "drift": drift_result, "alerts": alerts,
        "training": {"strategy": "directa por horizonte", "known_features": ["calendario","histórico hasta el corte","producto","color","categoría"], "unknown_features_excluded": ["venta futura","pedido futuro no registrado","entrega futura"], "duration_seconds": 0.0},
    }


def build_payload(path: Path, objective: str = "Venta") -> dict:
    return build_payload_from_series(load_series(path, objective), objective)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--objective", default="Venta", choices=("Venta", "Pedido"))
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    payload = build_payload(args.input, args.objective)
    if "training" in payload: payload["training"]["duration_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 3)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
