"""Build reproducible FENDI Walmart engine and dashboard inputs from PRD 01 facts."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


PRIMARY_2024 = "Estadistica Venta Resurtible WM 2024 Dic 2024.xlsx"
MASTER_2026 = "Estadistica Todas las Cadenas Cierre de Julio 2026.xlsx"
OBJECTIVES = {"Venta", "Pedido"}
DASHBOARD_METRICS = ("Fcst Cliente", "Fcst Towell", "Venta", "Pedido", "Entrega", "Inventario")


def number(value: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def eligible(row: dict[str, str]) -> bool:
    if row.get("family", "").strip().upper() != "FENDI":
        return False
    period = row.get("period", "")
    source = row.get("source_file", "")
    if period.startswith("2024"):
        return source == PRIMARY_2024 and row.get("chain_code") == "BD"
    return period >= "2025-01" and source == MASTER_2026 and row.get("chain_code") == "WM"


def build(facts_path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    with facts_path.open(encoding="utf-8-sig", newline="") as handle:
        facts = [row for row in csv.DictReader(handle) if eligible(row)]

    selected: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in facts:
        if row["metric"] not in OBJECTIVES or not row.get("period") or not row.get("upc"):
            continue
        selected[(row["upc"], row["period"], row["metric"])] = row

    series: list[dict[str, object]] = []
    for row in sorted(selected.values(), key=lambda item: (item["metric"], item["upc"], item["period"])):
        value = number(row.get("value", ""))
        series.append(
            {
                "tenant": "Towell",
                "chain": "Walmart",
                "chain_code": "WM",
                "pilot_scope": "FENDI BD / familia FENDI en Walmart",
                "canonical_product_id": row["upc"],
                "item": row["item"],
                "upc": row["upc"],
                "description": row["description"],
                "objective": row["metric"],
                "unit": row["unit"],
                "period": row["period"],
                "value": "" if value is None else value,
                "is_observed_zero": value == 0,
                "is_missing": value is None,
                "close_status": row["close_status"],
                "source_file": row["source_file"],
                "source_sheet": row["sheet"],
                "source_row": row["source_row"],
                "source_cell": row["source_cell"],
                "record_hash": row["record_hash"],
                "selection_rule": "2024=Base del cierre 2024; 2025-2026=BAASE del cierre julio 2026; solo Walmart + familia FENDI.",
            }
        )

    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    lineage: dict[str, set[str]] = defaultdict(set)
    for row in facts:
        metric = row.get("metric", "")
        period = row.get("period", "")
        if metric not in DASHBOARD_METRICS or not period:
            continue
        value = number(row.get("value", ""))
        if value is not None:
            totals[period][metric] += value
            lineage[period].add(f"{row['source_file']}::{row['sheet']}")

    history = []
    for period in sorted(totals):
        if period < "2025-01":
            continue
        values = totals[period]
        sale = values.get("Venta")
        towell = values.get("Fcst Towell")
        wape = None if not sale else round(100 * abs(sale - (towell or 0)) / sale, 1)
        history.append(
            {
                "period": period,
                "client": round(values.get("Fcst Cliente", 0)),
                "towell": round(values.get("Fcst Towell", 0)),
                "sale": round(values.get("Venta", 0)),
                "order": round(values.get("Pedido", 0)),
                "delivery": round(values.get("Entrega", 0)),
                "inventory": round(values.get("Inventario", 0)),
                "wape_reference": wape,
                "sources": sorted(lineage[period]),
            }
        )

    dashboard = {
        "scope": "Walmart · familia FENDI",
        "cutoff": history[-1]["period"] if history else "",
        "history": history,
        "audit": {
            "source_rows": len(facts),
            "products": len({row["upc"] for row in facts if row.get("upc")}),
            "objectives": sorted(OBJECTIVES),
            "selection": "Solo registros Walmart de la familia FENDI; no se agregan otras familias ni cadenas.",
            "screenshot_control": "Los valores 74,942, 103,803 y 124,151 del cierre 2024 corresponden a Existencia mensual, no a Venta ni Pedido.",
        },
    }
    return series, dashboard


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts", required=True, type=Path)
    parser.add_argument("--series-output", required=True, type=Path)
    parser.add_argument("--dashboard-output", required=True, type=Path)
    args = parser.parse_args()
    series, dashboard = build(args.facts)
    args.series_output.parent.mkdir(parents=True, exist_ok=True)
    with args.series_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(series[0]))
        writer.writeheader()
        writer.writerows(series)
    args.dashboard_output.parent.mkdir(parents=True, exist_ok=True)
    args.dashboard_output.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"series_rows": len(series), "history_periods": len(dashboard["history"]), "cutoff": dashboard["cutoff"]}))


if __name__ == "__main__":
    main()
