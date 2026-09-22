"""Read-only forecast and performance tools. Every value comes from DataProvider."""

from __future__ import annotations

import math
import unicodedata
from typing import Any

from .data_provider import DataProvider


def fold(value: str | None) -> str:
    plain = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in plain if not unicodedata.combining(char)).casefold().strip()


def _match_product(provider: DataProvider, query: dict[str, Any]) -> tuple[str | None, str | None]:
    wanted = fold(query.get("product") or query.get("color"))
    if not wanted or wanted in {"todos", "todas", "fendi bd", "total", "consolidado"}:
        return None, None
    series = provider.load("statistical")["series"]
    products = {row["series_id"]: row["label"] for row in series if row.get("target") == "Venta" and row["series_id"] != "total-fendi-bd"}
    for series_id, label in products.items():
        if wanted == fold(series_id) or wanted == fold(label) or wanted in fold(label):
            return series_id, label
    return "", query.get("product") or query.get("color")


def _selected(provider: DataProvider, query: dict[str, Any], target: str = "Venta") -> tuple[dict[str, Any] | None, str | None]:
    series_id, label = _match_product(provider, query)
    if series_id == "":
        return None, label
    key = series_id or "total-fendi-bd"
    row = next((item for item in provider.load("statistical")["series"] if item["series_id"] == key and item.get("target") == target), None)
    return row, label


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {"available": False, "reason": reason, **extra}


class ForecastTools:
    def __init__(self, provider: DataProvider):
        self.provider = provider

    def get_current_forecast(self, query: dict[str, Any]) -> dict[str, Any]:
        product, label = _match_product(self.provider, query)
        if product:
            return _unavailable("No hay Forecast Towell final publicado para el producto seleccionado.", product=label)
        if product == "":
            return _unavailable("Producto no encontrado.", product=label)
        payload = self.provider.load("ensemble")
        points = payload["forecast_towell"]
        point = next((row for row in points if row["series_id"] == "total-fendi-bd"), None)
        if not point:
            return _unavailable("No hay forecast vigente.")
        probability = point["probability"]
        return {
            "available": True, "period": point["period"], "chain": self.provider.load("statistical")["chain"],
            "series_id": point["series_id"], "forecast_towell": point["value"],
            "motor": payload["selection"]["official"]["strategy"], "version": payload["version"],
            "p10": probability.get("p10"), "p50": probability.get("p50"),
            "p90": probability.get("p90"), "p95": probability.get("p95"),
            "confidence": point.get("confidence"), "cutoff": payload["cutoff"],
        }

    def get_forecast_12m(self, query: dict[str, Any]) -> dict[str, Any]:
        product, label = _match_product(self.provider, query)
        if product or product == "":
            return _unavailable("No hay horizonte final publicado para el producto seleccionado.", product=label)
        payload = self.provider.load("ensemble")
        points = [row for row in payload["forecast_towell"] if row["series_id"] == "total-fendi-bd"]
        return {"available": len(points) == 12, "cutoff": payload["cutoff"], "version": payload["version"],
                "horizons": [{"horizon": row["horizon"], "period": row["period"], "forecast_towell": row["value"]} for row in points]}

    def get_wape_summary(self, query: dict[str, Any]) -> dict[str, Any]:
        row, label = _selected(self.provider, query)
        if row is None:
            return _unavailable("Producto no encontrado.", product=label)
        payload = self.provider.load("ensemble")
        ml = self.provider.load("ml")
        if row["series_id"] == "total-fendi-bd":
            client_rows = [item for item in self.provider.load("dashboard")["history"]
                           if item["period"] <= payload["cutoff"] and item.get("sale") is not None
                           and item.get("client") is not None]
            client_denominator = sum(abs(item["sale"]) for item in client_rows)
            client_wape = (100 * sum(abs(item["sale"] - item["client"]) for item in client_rows)
                           / client_denominator) if client_denominator else None
            return {"available": True, "level": "total_fendi_bd", "period_evaluated": payload["cutoff"],
                    "forecast_towell": payload["selection"]["official"]["wape"],
                    "statistical": payload["selection"]["incumbent"]["wape"],
                    "ml": payload["selection"]["official"]["wape"] if payload["selection"]["official"]["strategy"] == "ml" else None,
                    "ml_product_month_internal": ml["champion"]["wape"],
                    "client": round(client_wape, 4) if client_wape is not None else None,
                    "client_period_evaluated": [client_rows[0]["period"], client_rows[-1]["period"]] if client_rows else None,
                    "client_basis": "closed_dashboard_history", "basis": "backtest_aligned_total"}
        backtest = [item for item in ml.get("backtest", []) if item["series_id"] == row["series_id"] and item.get("actual") is not None]
        denominator = sum(abs(item["actual"]) for item in backtest)
        ml_wape = 100 * sum(abs(item["actual"] - item["forecast"]) for item in backtest) / denominator if denominator else None
        return {"available": row.get("wape") is not None or ml_wape is not None,
                "reason": "Aún no hay WAPE válido para este producto.",
                "level": "product", "series_id": row["series_id"],
                "product": row["label"], "period_evaluated": row.get("last_closed_period"),
                "forecast_towell": None, "statistical": row.get("wape"),
                "ml": round(ml_wape, 4) if ml_wape is not None else None,
                "client": None, "basis": "product_model_backtest",
                "ml_basis": "one_month_ahead", "statistical_basis": "rolling_horizons"}

    def get_bias_summary(self, query: dict[str, Any]) -> dict[str, Any]:
        row, label = _selected(self.provider, query)
        if row is None:
            return _unavailable("Producto no encontrado.", product=label)
        ensemble = self.provider.load("ensemble")
        total = row["series_id"] == "total-fendi-bd"
        bias = ensemble["selection"]["official"]["bias"] if total else row.get("bias")
        if bias is None:
            return _unavailable("Bias no disponible para esta serie.", product=label)
        return {"available": True, "bias": bias, "direction": "subpronóstico" if bias > 0 else "sobrepronóstico" if bias < 0 else "sin sesgo",
                "period_evaluated": ensemble["cutoff"] if total else row.get("last_closed_period"),
                "level": "total_fendi_bd" if total else "product", "product": None if total else row["label"],
                "convention": "real_menos_pronostico"}

    def get_fill_rate(self, query: dict[str, Any]) -> dict[str, Any]:
        product, label = _match_product(self.provider, query)
        if product or product == "":
            return _unavailable("Entrega real por producto no está disponible en los registros consolidados.", product=label)
        history = self.provider.load("dashboard")["history"]
        period = query.get("period") or history[-1]["period"]
        row = next((item for item in history if item["period"] == period), None)
        if row is None and not query.get("period_explicit"):
            row = history[-1]
            period = row["period"]
        if not row:
            return _unavailable("No hay Pedido y Entrega reales para ese periodo.", period=period)
        order, delivery = row.get("order"), row.get("delivery")
        if order is None or delivery is None or order == 0 and delivery > 0:
            return _unavailable("Fill Rate indefinido para ese periodo.", period=period)
        rate = 100.0 if order == 0 and delivery == 0 else 100 * delivery / order
        return {"available": True, "period": period, "chain": "Walmart", "pedido_real": order,
                "entrega_real": delivery, "fill_rate": round(rate, 4), "formula": "entrega_real / pedido_real"}

    def get_champion_status(self, query: dict[str, Any]) -> dict[str, Any]:
        ensemble = self.provider.load("ensemble")
        official = ensemble["selection"]["official"]
        ml = self.provider.load("ml")
        stat = self.provider.load("statistical")
        is_ml = official["strategy"] == "ml"
        return {"available": True, "motor": official["strategy"],
                "model": ml["champion"]["model"] if is_ml else next((s["winner"] for s in stat["series"] if s["series_id"] == "total-fendi-bd" and s["target"] == "Venta"), None),
                "version": ml["champion"]["version"] if is_ml else stat["run"]["version"],
                "forecast_version": ensemble["version"], "wape": official["wape"],
                "state": official.get("state", "champion"), "evaluation_date": ensemble["generated_at"],
                "level": "total_fendi_bd", "authorized_promotion": ensemble["publication"].get("authorized_promotion", False)}

    def get_challenger_status(self, query: dict[str, Any]) -> dict[str, Any]:
        ml = self.provider.load("ml")
        candidate = ml.get("challenger")
        if not candidate:
            return _unavailable("No hay Challenger registrado.")
        return {"available": True, "model": candidate["model"], "version": candidate["version"],
                "wape": candidate.get("wape"), "state": candidate.get("status"),
                "validation_closures": None, "evidence": "backtesting temporal producto-mes",
                "evaluation_date": ml["generated_at"], "published_as_forecast_towell": False}

    def get_forecast_comparison(self, query: dict[str, Any]) -> dict[str, Any]:
        ensemble = self.provider.load("ensemble")
        official, baseline = ensemble["selection"]["official"], ensemble["selection"]["incumbent"]
        return {"available": True, "period_evaluated": ensemble["cutoff"], "forecast_towell_wape": official["wape"],
                "statistical_wape": baseline["wape"], "ml_internal_wape": self.provider.load("ml")["champion"]["wape"],
                "improvement_points": round(baseline["wape"] - official["wape"], 4), "official_motor": official["strategy"]}

    def get_product_performance(self, query: dict[str, Any]) -> dict[str, Any]:
        row, label = _selected(self.provider, query)
        if row is None:
            return _unavailable("Producto no encontrado.", product=label)
        if row["series_id"] == "total-fendi-bd":
            return _unavailable("Indica un producto o color para consultar su desempeño.")
        if query.get("category") and fold(query["category"]) not in {"fendi bd", "todas", "todos"}:
            return _unavailable("Categoría fuera del piloto FENDI BD.")
        period = query.get("period")
        history = [point for point in row.get("history", []) if not period or point["period"] == period]
        if not history and not query.get("period_explicit"):
            history = row.get("history", [])[-3:]
            period = row.get("last_closed_period")
        if period and not history:
            return _unavailable("No hay observación de ese producto en el periodo solicitado.", period=period)
        return {"available": True, "series_id": row["series_id"], "product": row["label"],
                "category": "FENDI BD", "color": row["label"], "period": period or row.get("last_closed_period"),
                "wape": row.get("wape"), "bias": row.get("bias"), "model": row.get("winner"),
                "observations": history if period else history[-3:], "evidence": row.get("status")}

    def get_highest_error_series(self, query: dict[str, Any]) -> dict[str, Any]:
        valid = [row for row in self.provider.load("statistical")["series"]
                 if row.get("target") == "Venta" and row["series_id"] != "total-fendi-bd"
                 and isinstance(row.get("wape"), (int, float)) and math.isfinite(row["wape"])]
        if not valid:
            return _unavailable("No hay WAPE válido por producto.")
        worst = max(valid, key=lambda row: row["wape"])
        return {"available": True, "series_id": worst["series_id"], "product": worst["label"],
                "wape": worst["wape"], "period_evaluated": worst.get("last_closed_period"),
                "model": worst.get("winner"), "level": "product"}

    def get_forecast_vintage(self, query: dict[str, Any]) -> dict[str, Any]:
        issue, target = query.get("issue_period"), query.get("target_period")
        rows = [row for row in self.provider.vintages()
                if (not issue or row.get("issue_period") == issue) and (not target or row.get("target_period") == target)]
        product, label = _match_product(self.provider, query)
        if product == "":
            return _unavailable("Producto no encontrado.", product=label)
        if product:
            rows = [row for row in rows if row.get("series_id") == product]
        if not rows:
            return _unavailable("No existe un vintage persistido para esa consulta.", issue_period=issue, target_period=target)
        return {"available": True, "vintages": rows}

    def get_probability_bands(self, query: dict[str, Any]) -> dict[str, Any]:
        product, label = _match_product(self.provider, query)
        if product or product == "":
            return _unavailable("No hay bandas finales publicadas para el producto seleccionado.", product=label)
        payload = self.provider.load("ensemble")
        period = query.get("period") or payload["forecast_towell"][0]["period"]
        row = next((item for item in payload["forecast_towell"] if item["series_id"] == "total-fendi-bd" and item["period"] == period), None)
        if row is None:
            return _unavailable("No hay bandas publicadas para ese periodo.", period=period)
        return {"available": True, "period": period, "version": payload["version"], **row["probability"]}

    def get_drift_status(self, query: dict[str, Any]) -> dict[str, Any]:
        ml = self.provider.load("ml")
        drift = ml["drift"]
        return {"available": True, "detected": drift["status"] == "alert", "severity": "warning" if drift["status"] == "alert" else "none",
                "series": "total-fendi-bd", "evaluation_date": ml["generated_at"],
                "signal_type": "cambio de nivel reciente", "score": drift["score"], "state": drift["status"]}

    def get_decision_history(self, query: dict[str, Any]) -> dict[str, Any]:
        period = query.get("period")
        rows = []
        for stored in self.provider.decisions():
            if "decision" in stored:
                decision = stored["decision"]
                evaluation = stored.get("evaluation") or {}
                actual_by_key = {
                    (item.get("series_id"), item.get("horizon")): item.get("actual")
                    for item in evaluation.get("details", [])
                }
                for entry in decision.get("entries", []):
                    rows.append({
                        "target_period": decision.get("target_period"),
                        "series_id": entry.get("series_id"),
                        "forecast_towell": entry.get("forecast_towell"),
                        "adjustment": entry.get("adjustment"),
                        "forecast_approved": entry.get("forecast_approved"),
                        "reason": entry.get("reason"),
                        "actual": actual_by_key.get((entry.get("series_id"), entry.get("horizon"))),
                        "decision_version": decision.get("decision_version"),
                    })
            else:
                rows.append(stored)
        rows = [row for row in rows if not period or row.get("target_period") == period]
        if not rows:
            return _unavailable("No hay decisiones gerenciales reales registradas para ese periodo.", period=period)
        return {"available": True, "decisions": rows}

    def get_fva_summary(self, query: dict[str, Any]) -> dict[str, Any]:
        evaluated = []
        for row in self.provider.decisions():
            metric = row.get("evaluation", row)
            if metric.get("towell_wape") is not None and metric.get("approved_wape") is not None:
                evaluated.append(metric)
        if not evaluated:
            return _unavailable("FVA aún no evaluable: faltan decisiones reales con venta cerrada.")
        weights = [sum(abs(item.get("actual") or 0) for item in row.get("details", [])) for row in evaluated]
        if len(evaluated) > 1 and not all(weights):
            return _unavailable("FVA agregado no evaluable: faltan cantidades reales para ponderar las decisiones.")
        weights = [weight or 1 for weight in weights]
        total_weight = sum(weights)
        base = sum(row["towell_wape"] * weight for row, weight in zip(evaluated, weights)) / total_weight
        approved = sum(row["approved_wape"] * weight for row, weight in zip(evaluated, weights)) / total_weight
        return {"available": True, "decisions_evaluated": len(evaluated), "towell_wape": base,
                "approved_wape": approved, "fva_points": round(base - approved, 4),
                "classification": "mejora" if approved < base else "empeora" if approved > base else "neutro",
                "basis": "weighted_by_actual"}

    def get_period_status(self, query: dict[str, Any]) -> dict[str, Any]:
        dashboard = self.provider.load("dashboard")
        return {"available": True, "last_closed_with_data": dashboard["cutoff"],
                "requested_period": query.get("period"),
                "requested_period_state": "cerrado_con_datos" if query.get("period") and query["period"] <= dashboard["cutoff"] else "no_disponible",
                "source": "normalized_platform_records"}


TOOL_METHODS = {
    "current_forecast": "get_current_forecast", "forecast_12m": "get_forecast_12m",
    "wape_summary": "get_wape_summary", "bias_summary": "get_bias_summary",
    "fill_rate": "get_fill_rate", "champion_status": "get_champion_status",
    "challenger_status": "get_challenger_status", "forecast_comparison": "get_forecast_comparison",
    "product_performance": "get_product_performance", "highest_error_series": "get_highest_error_series",
    "forecast_vintage": "get_forecast_vintage", "probability_bands": "get_probability_bands",
    "drift_status": "get_drift_status", "decision_history": "get_decision_history",
    "fva_summary": "get_fva_summary", "period_status": "get_period_status",
}
