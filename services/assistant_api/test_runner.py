from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from services.assistant_api.data_provider import NormalizedDataProvider
from services.assistant_api.runner import EnginePipeline, LocalResearchProvider, MonthlyForecastRunner, ResearchProvider


class SpyResearch(ResearchProvider):
    def __init__(self, events: list[str]):
        self.events = events

    def run(self, cutoff_date: str, chain: str, category: str | None = None, product: str | None = None):
        self.events.append("research")
        return LocalResearchProvider().run(cutoff_date, chain, category, product)


class LeakyResearch(ResearchProvider):
    def run(self, cutoff_date: str, chain: str, category: str | None = None, product: str | None = None):
        result = LocalResearchProvider().run(cutoff_date, chain, category, product)
        result["signals"] = [{"published_at": "2026-08-01", "type": "future"}]
        return result


class StubPipeline(EnginePipeline):
    def __init__(self, provider: NormalizedDataProvider, events: list[str], ml_fails: bool = False, ensemble_fails: bool = False):
        self.provider, self.events = provider, events
        self.ml_fails, self.ensemble_fails = ml_fails, ensemble_fails

    def statistical(self, normalized_csv: Path):
        self.events.append("statistical")
        with normalized_csv.open(encoding="utf-8", newline="") as handle:
            assert max(row["period"] for row in csv.DictReader(handle)) == "2026-07"
        return self.provider.load("statistical")

    def ml(self, normalized_csv: Path):
        self.events.append("ml")
        if self.ml_fails:
            raise RuntimeError("ml_failed")
        return self.provider.load("ml")

    def ensemble(self, normalized_csv: Path, statistical: dict, ml: dict | None):
        self.events.append("ensemble")
        if self.ensemble_fails:
            raise RuntimeError("ensemble_failed")
        if ml is None:
            payload = self.provider.load("ensemble")
            payload["selection"]["official"] = {"strategy": "statistical", "wape": 19.1503}
            return payload
        return self.provider.load("ensemble")


class RunnerTests(unittest.TestCase):
    def test_research_precedes_engines_and_vintage_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            events: list[str] = []
            provider = NormalizedDataProvider(state_dir=Path(directory))
            runner = MonthlyForecastRunner(provider, SpyResearch(events), StubPipeline(provider, events),
                                           state_dir=Path(directory))
            result = runner.run_month("2026-07")
            self.assertEqual(result["state"], "Completed")
            self.assertEqual(events, ["research", "statistical", "ml", "ensemble"])
            self.assertTrue(Path(result["research_snapshot_path"]).exists())
            vintages = json.loads((Path(directory) / "vintages.json").read_text(encoding="utf-8"))
            self.assertEqual(len(vintages), 12)
            self.assertTrue(all(row["issue_period"] == "2026-07" for row in vintages))

    def test_future_data_is_excluded_and_missing_cutoff_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            events: list[str] = []
            provider = NormalizedDataProvider(state_dir=Path(directory))
            runner = MonthlyForecastRunner(provider, SpyResearch(events), StubPipeline(provider, events),
                                           state_dir=Path(directory))
            failed = runner.run_month("2026-08")
            self.assertEqual(failed["state"], "Failed")
            self.assertIn("cutoff_data_missing", str(failed["errors"]))
            self.assertEqual(events, [])
            historical = runner.run_month("2026-06")
            self.assertEqual(historical["state"], "Failed")
            self.assertIn("availability_metadata_missing", str(historical["errors"]))

    def test_future_research_is_rejected_before_any_motor(self):
        with tempfile.TemporaryDirectory() as directory:
            events: list[str] = []
            provider = NormalizedDataProvider(state_dir=Path(directory))
            runner = MonthlyForecastRunner(provider, LeakyResearch(),
                                           StubPipeline(provider, events), state_dir=Path(directory))
            result = runner.run_month("2026-07")
            self.assertEqual(result["state"], "Failed")
            self.assertEqual(events, [])
            self.assertIn("research_leakage_detected", str(result["errors"]))

    def test_ml_failure_falls_back_and_ensemble_preserves_published_champion(self):
        with tempfile.TemporaryDirectory() as directory:
            events: list[str] = []
            provider = NormalizedDataProvider(state_dir=Path(directory))
            runner = MonthlyForecastRunner(provider, SpyResearch(events),
                                           StubPipeline(provider, events, ml_fails=True),
                                           state_dir=Path(directory))
            result = runner.run_month("2026-07")
            self.assertEqual(result["state"], "Completed")
            self.assertEqual(result["results"]["ensemble"]["selection"]["official"]["strategy"], "statistical")
            self.assertIn("statistical", str(result["errors"]))
        with tempfile.TemporaryDirectory() as directory:
            events = []
            provider = NormalizedDataProvider(state_dir=Path(directory))
            runner = MonthlyForecastRunner(provider, SpyResearch(events),
                                           StubPipeline(provider, events, ensemble_fails=True),
                                           state_dir=Path(directory))
            result = runner.run_month("2026-07")
            self.assertEqual(result["state"], "Completed")
            self.assertEqual(result["results"]["ensemble"]["selection"]["official"]["strategy"], "ml")
            self.assertIn("retained_published_champion", str(result["errors"]))


if __name__ == "__main__":
    unittest.main()
