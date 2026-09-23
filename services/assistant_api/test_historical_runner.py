from __future__ import annotations

import csv
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from services.assistant_api.data_provider import DataProvider, NormalizedDataProvider
from services.assistant_api.historical_runner import HistoricalForecastRunner
from services.assistant_api.runner import EnginePipeline, LocalResearchProvider, ResearchProvider


def next_month(period: str, offset: int) -> str:
    year, month = map(int, period.split("-"))
    total = year * 12 + month - 1 + offset
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def source_rows() -> list[dict[str, str]]:
    rows = [{"chain": "Walmart", "pilot_scope": "OTHER 2023", "objective": "Venta",
             "canonical_product_id": "other", "period": "2023-12", "value": "999",
             "available_at": "2023-12-31", "is_missing": "False", "close_status": "closed"}]
    for offset in range(8):
        period = next_month("2024-01", offset)
        rows.append({"chain": "Walmart", "pilot_scope": "FENDI BD", "objective": "Venta",
                     "canonical_product_id": "sku-1", "period": period, "value": str(101 + offset),
                     "available_at": f"{period}-28", "is_missing": "False", "close_status": "closed"})
        rows.append({"chain": "Walmart", "pilot_scope": "FENDI BD", "objective": "Pedido",
                     "canonical_product_id": "sku-1", "period": period, "value": str(120 + offset),
                     "available_at": f"{period}-28", "is_missing": "False", "close_status": "closed"})
    rows.append({"chain": "Walmart", "pilot_scope": "FENDI BD", "objective": "Venta",
                 "canonical_product_id": "sku-1", "period": "2024-09", "value": "99999",
                 "available_at": "2024-09-30", "is_missing": "False", "close_status": "open"})
    for row in rows:
        row.update({"availability_source": "system_timestamp",
                    "availability_confidence": "verified",
                    "availability_rule_id": "DIRECT_TIMESTAMP_V1"})
    return rows


class MemoryProvider(DataProvider):
    def __init__(self, rows: list[dict[str, str]]):
        self.rows = rows

    @property
    def name(self) -> str:
        return "memory-normalized-test"

    def records(self) -> list[dict[str, str]]:
        return list(self.rows)

    def load(self, name: str) -> dict:
        raise AssertionError("historical replay must not load current published Champion")

    def decisions(self) -> list[dict]:
        return []

    def vintages(self) -> list[dict]:
        return []


class FakePipeline(EnginePipeline):
    def __init__(self):
        self.events: list[str] = []
        self.future_ml = False
        self.fail_period: str | None = None
        self.runner: HistoricalForecastRunner | None = None
        self.cancel_period: str | None = None
        self.pause_period: str | None = None
        self.last_rows: list[dict[str, str]] = []

    def statistical(self, normalized_csv: Path) -> dict:
        self.events.append("statistical")
        with normalized_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.last_rows = rows
        period = max(row["period"] for row in rows if row["objective"] == "Venta")
        if period == self.fail_period:
            raise RuntimeError("controlled_stat_failure")
        if period == self.cancel_period and self.runner:
            self.runner.cancel("HRUN-FENDI-001")
        if period == self.pause_period and self.runner:
            self.runner.pause("HRUN-FENDI-001")
        history = [{"period": row["period"], "actual": float(row["value"]), "forecast": 100.0}
                   for row in rows if row["objective"] == "Venta"]
        return {"run": {"cutoff": period, "engine_version": "stat-test", "version": "stat-test"},
                "series": [{"series_id": "total-fendi-bd", "target": "Venta", "status": "completed",
                            "wape": 10.0, "bias": 2.0, "history": history,
                            "forecast": [{"period": next_month(period, h), "forecast": 100.0}
                                         for h in range(1, 13)]}]}

    def ml(self, normalized_csv: Path) -> dict:
        self.events.append("ml")
        with normalized_csv.open(encoding="utf-8", newline="") as handle:
            period = max(row["period"] for row in csv.DictReader(handle) if row["objective"] == "Venta")
        return {"cutoff": "2025-01" if self.future_ml else period,
                "engine_version": "ml-test", "champion": {"wape": 8.0},
                "drift": {"status": "stable"}}

    def ensemble(self, normalized_csv: Path, statistical: dict, ml: dict | None) -> dict:
        self.events.append("ensemble")
        period = statistical["run"]["cutoff"]
        if ml is None:
            raise ValueError("no_ml")
        return {"version": "unstable-version", "cutoff": period, "engine_version": "ensemble-test",
                "selection": {"official": {"strategy": "ml", "wape": 8.0}, "challenger": None},
                "forecast_towell": [
                    {"series_id": "total-fendi-bd", "period": next_month(period, h), "horizon": h,
                     "value": 100.0, "probability": {"p10": 90.0, "p50": 100.0,
                                                     "p90": 110.0, "p95": 120.0}}
                    for h in range(1, 13)]}


class BrokenResearch(ResearchProvider):
    def run(self, cutoff_date: str, chain: str, category: str | None = None,
            product: str | None = None, historical_context: dict | None = None) -> dict:
        raise RuntimeError("research_unavailable")


class HistoricalRunnerTests(unittest.TestCase):
    def make_runner(self, directory: str):
        pipeline = FakePipeline()
        source_dir = Path(directory) / "inputs"
        source_dir.mkdir()
        (source_dir / "2024-07.json").write_text(json.dumps({
            "sources": [{"published_at": "2024-07-20", "url": "local-valid"},
                        {"published_at": "2024-08-01", "url": "future-excluded"}],
            "signals": []}), encoding="utf-8")
        runner = HistoricalForecastRunner(MemoryProvider(source_rows()),
                                          LocalResearchProvider(source_dir), pipeline,
                                          state_dir=Path(directory) / "state")
        pipeline.runner = runner
        return runner, pipeline

    def test_research_precedes_data_and_future_rows_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            result = runner.run_month("2024-07")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual([event["step"] for event in result["events"][:2]], ["RESEARCH", "DATA_PREP"])
            self.assertEqual(pipeline.events, ["statistical", "ml", "ensemble"])
            self.assertNotIn("99999", [row["value"] for row in pipeline.last_rows])
            research = json.loads((runner.state_dir / "research" / f"{result['research_snapshot_id']}.json").read_text())
            self.assertTrue(research["frozen"])
            self.assertEqual(research["source_count"], 1)
            self.assertEqual(research["excluded_after_cutoff"], 1)
            data = json.loads((runner.state_dir / "data" / f"{result['data_snapshot_id']}.json").read_text())
            self.assertTrue(all(row["period"] <= "2024-07" for row in data["rows"]))
            self.assertTrue(all(row["available_at"] <= "2024-07-31" for row in data["rows"]))
            self.assertEqual(data["excluded"]["available_after_cutoff"], 3)
            vintage = json.loads((runner.state_dir / "vintages" / f"{result['vintage_id']}.json").read_text())
            self.assertEqual(len(vintage["forecasts"]), 12)
            self.assertEqual(vintage["forecasts"][0]["probability"]["p95"], 120.0)
            self.assertEqual(result["evaluation"]["rows"][0]["actual"], 108.0)
            self.assertEqual(result["evaluation"]["rows"][1]["evaluation_status"], "pending")

    def test_prelaunch_and_missing_availability_are_not_fabricated(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            before = runner.run_month("2023-12")
            self.assertEqual(before["status"], "SKIPPED_INSUFFICIENT_HISTORY")
            self.assertIsNone(before["history"]["earliest_available_period"])
            rows = source_rows()
            for row in rows:
                row.pop("available_at", None)
            another = HistoricalForecastRunner(MemoryProvider(rows), pipeline=FakePipeline(),
                                               state_dir=Path(directory) / "unverified")
            skipped = another.run_month("2024-07")
            self.assertEqual(skipped["status"], "SKIPPED_INSUFFICIENT_HISTORY")
            self.assertEqual(skipped["history"]["consecutive_active_periods"], 0)
            self.assertEqual(pipeline.events, [])

    def test_research_failure_blocks_models(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = FakePipeline()
            runner = HistoricalForecastRunner(MemoryProvider(source_rows()), BrokenResearch(), pipeline,
                                              state_dir=Path(directory))
            result = runner.run_month("2024-07")
            self.assertEqual(result["status"], "RESEARCH_FAILED")
            self.assertEqual(pipeline.events, [])

    def test_future_model_is_not_used_and_statistical_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            pipeline.future_ml = True
            result = runner.run_month("2024-07")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["champion"]["strategy"], "statistical")
            self.assertIn("future_ml_model", str(result["warnings"]))
            self.assertEqual(len(result["evaluation"]["rows"]), 12)

    def test_idempotence_force_rerun_and_range_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            first = runner.run_month("2024-07")
            same = runner.run_month("2024-07")
            self.assertEqual(first["run_id"], same["run_id"])
            self.assertEqual(first["vintage_hash"], same["vintage_hash"])
            rerun = runner.run_month("2024-07", force_rerun=True)
            self.assertNotEqual(first["run_id"], rerun["run_id"])
            old_vintage = json.loads((runner.state_dir / "vintages" / f"{first['vintage_id']}.json").read_text())
            new_vintage = json.loads((runner.state_dir / "vintages" / f"{rerun['vintage_id']}.json").read_text())
            self.assertEqual([row["value"] for row in old_vintage["forecasts"]],
                             [row["value"] for row in new_vintage["forecasts"]])
            self.assertTrue((runner.state_dir / "vintages" / f"{first['vintage_id']}.json").exists())
            pipeline.fail_period = "2024-08"
            job = runner.run_range("2024-06", "2024-08")
            self.assertEqual(job["status"], "FAILED")
            self.assertEqual(job["summary"]["earliest_forecastable_period"], "2024-07")
            pipeline.fail_period = None
            resumed = runner.resume(job["run_id"], resume_from="2024-08")
            self.assertEqual(resumed["status"], "COMPLETED_WITH_WARNINGS")
            self.assertEqual(resumed["summary"]["periods_executed"], 2)
            self.assertEqual(resumed["summary"]["periods_skipped"], 1)
            self.assertEqual(resumed["summary"]["horizon_count"], 24)
            self.assertEqual(resumed["summary"]["by_horizon"]["1"]["observations"], 1)

    def test_cancel_does_not_save_partial_vintage(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            pipeline.cancel_period = "2024-07"
            job = runner.run_range("2024-07", "2024-08")
            self.assertEqual(job["status"], "CANCELLED")
            self.assertEqual(list((runner.state_dir / "vintages").glob("*.json")) if
                             (runner.state_dir / "vintages").exists() else [], [])

    def test_pause_preserves_completed_month_then_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            pipeline.pause_period = "2024-07"
            job = runner.run_range("2024-07", "2024-08")
            self.assertEqual(job["status"], "PAUSED")
            self.assertEqual(job["summary"]["vintage_count"], 1)
            pipeline.pause_period = None
            resumed = runner.resume(job["run_id"], resume_from="2024-08")
            self.assertEqual(resumed["status"], "COMPLETED")
            self.assertEqual(resumed["summary"]["vintage_count"], 2)

    def test_real_pilot_without_availability_is_conservatively_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = HistoricalForecastRunner(NormalizedDataProvider(), state_dir=Path(directory))
            job = runner.run_range("2023-12", "2024-02")
            self.assertEqual(job["summary"]["earliest_source_period"], "2024-01")
            self.assertEqual(job["summary"]["first_nonzero_source_period"], "2024-09")
            self.assertEqual(job["summary"]["earliest_theoretical_period_unverified"], "2025-03")
            self.assertEqual(job["summary"]["periods_executed"], 0)
            self.assertEqual(job["summary"]["periods_skipped"], 3)

    def test_async_range_and_research_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.make_runner(directory)
            job = asyncio.run(runner.run_range_async("2024-07", "2024-07"))
            self.assertEqual(job["status"], "COMPLETED")
            child = json.loads((runner.state_dir / "runs" / f"{job['children']['2024-07']}.json").read_text())
            path = runner.state_dir / "research" / f"{child['research_snapshot_id']}.json"
            tampered = json.loads(path.read_text())
            tampered["sources"].append({"published_at": "2024-07-01", "url": "tampered"})
            path.write_text(json.dumps(tampered), encoding="utf-8")
            failed = runner.run_month("2024-07")
            self.assertEqual(failed["status"], "RESEARCH_FAILED")

    def test_parent_reuse_rejects_changed_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, _ = self.make_runner(directory)
            first = runner.run_range("2024-07", "2024-07")
            self.assertEqual(runner.run_range("2024-07", "2024-07")["run_id"], first["run_id"])
            runner.provider.rows.append({"chain": "Walmart", "pilot_scope": "FENDI BD",
                                         "objective": "Venta", "canonical_product_id": "sku-2",
                                         "period": "2024-07", "value": "5", "available_at": "2024-07-31",
                                         "availability_source": "system_timestamp",
                                         "availability_confidence": "verified",
                                         "is_missing": "False", "close_status": "closed"})
            with self.assertRaisesRegex(ValueError, "historical_inputs_changed_requires_force_rerun"):
                runner.run_range("2024-07", "2024-07")

    def test_first_vintage_is_frozen_with_manifest_and_no_future_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, pipeline = self.make_runner(directory)
            report = runner.first_vintage(start="2024-01", end="2024-08")
            self.assertTrue(report["first_real_vintage_validated"])
            self.assertEqual(report["period"], "2024-07")
            self.assertEqual(report["data_leakage"], 0)
            self.assertEqual(report["research_leakage"], 0)
            self.assertEqual(pipeline.events, ["statistical", "ml", "ensemble"])
            manifest = json.loads((runner.state_dir / "manifests" /
                                   f"{report['input_manifest_id']}.json").read_text())
            self.assertGreater(manifest["included_records"], 0)
            self.assertGreater(manifest["excluded_records"], 0)
            self.assertEqual(manifest["exclusion_reasons"]["available_after_cutoff"], 3)
            vintage = json.loads((runner.state_dir / "vintages" /
                                  f"{report['vintage_id']}.json").read_text())
            self.assertTrue(vintage["frozen"])
            self.assertEqual(vintage["input_manifest_hash"], manifest["hash"])


if __name__ == "__main__":
    unittest.main()
