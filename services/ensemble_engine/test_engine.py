import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from engine import BacktestRecord, EnsembleConfig, FutureRecord, candidate_weights, run_ensemble, select_strategy


def records(statistical, ml, actual=100.0, windows=3):
    return [
        BacktestRecord("total-fendi-bd", f"2025-{window:02d}", f"2026-{window:02d}", horizon, actual, statistical, ml)
        for horizon in range(1, 13) for window in range(1, windows + 1)
    ]


def future(statistical=90.0, ml=70.0):
    return [FutureRecord("total-fendi-bd", "Total FENDI BD", f"2027-{horizon:02d}", horizon, statistical, ml) for horizon in range(1, 13)]


class EnsembleAcceptanceTests(unittest.TestCase):
    def test_cp01_statistical_stays_champion(self):
        result=select_strategy(records(90,70),EnsembleConfig())
        self.assertEqual(result["official"]["strategy"],"statistical"); self.assertIsNone(result["challenger"])

    def test_cp02_ml_better_is_challenger(self):
        result=select_strategy(records(70,95),EnsembleConfig())
        self.assertEqual(result["challenger"]["strategy"],"ml"); self.assertEqual(result["official"]["strategy"],"statistical")

    def test_cp03_worse_ensemble_blocked(self):
        result=select_strategy(records(95,70),EnsembleConfig())
        rejected=[row for row in result["candidates"] if row["strategy"]=="ensemble" and row["wape"]>result["incumbent"]["wape"]]
        self.assertTrue(rejected); self.assertTrue(all(row["state"]=="rejected" for row in rejected))

    def test_cp04_better_ensemble_is_challenger(self):
        result=select_strategy(records(80,120),EnsembleConfig())
        self.assertEqual(result["challenger"]["strategy"],"ensemble"); self.assertAlmostEqual(result["challenger"]["statistical_weight"],.5)

    def test_cp05_insignificant_improvement_preserves_champion(self):
        result=select_strategy(records(90,90.02),EnsembleConfig(minimum_improvement=.25))
        self.assertIsNone(result["challenger"]); self.assertEqual(result["official"]["strategy"],"statistical")

    def test_cp06_weight_search_is_bounded_and_sums_to_one(self):
        result=select_strategy(records(80,120),EnsembleConfig())
        self.assertGreaterEqual(len(candidate_weights(EnsembleConfig())),11)
        self.assertLessEqual(len(result["candidates"]),19)
        self.assertTrue(all(abs(row["statistical_weight"]+row["ml_weight"]-1)<1e-9 for row in result["candidates"]))

    def test_cp07_ml_failure_uses_statistical(self):
        result=select_strategy(records(90,None),EnsembleConfig())
        self.assertEqual(result["official"]["strategy"],"statistical"); self.assertEqual(len(result["candidates"]),1)

    def test_cp08_high_divergence_alert(self):
        result=run_ensemble(records(90,70),future(100,150),"2026-07","STAT-V1","ML-V1")
        self.assertTrue(any(alert["type"]=="high_divergence" for alert in result["alerts"]))

    def test_cp09_new_close_reevaluates(self):
        before=select_strategy(records(90,70),EnsembleConfig())
        after=select_strategy(records(70,95),EnsembleConfig())
        self.assertNotEqual(before["decision"],after["decision"])

    def test_cp10_new_version_changes_with_cutoff(self):
        first=run_ensemble(records(90,70),future(),"2026-07","S1","M1")
        second=run_ensemble(records(90,70),future(),"2026-08","S1","M1")
        self.assertNotEqual(first["version"],second["version"])

    def test_cp11_vintage_values_include_issue_evidence(self):
        result=run_ensemble(records(90,70),future(),"2026-07","S1","M1")
        row=result["forecast_towell"][0]
        self.assertIn("statistical",row); self.assertIn("ml",row); self.assertIn("raw_value",row)

    def test_cp12_all_horizons_have_metrics(self):
        result=select_strategy(records(90,70),EnsembleConfig())
        self.assertEqual([row["horizon"] for row in result["official"]["by_horizon"]],list(range(1,13)))

    def test_cp13_empirical_probability_bands(self):
        varied=[]
        for horizon in range(1,13):
            for window,error in enumerate((-20,5,30),1):
                varied.append(BacktestRecord("total-fendi-bd",f"2025-{window:02d}",f"2026-{window:02d}",horizon,100,100-error,70))
        row=run_ensemble(varied,future(100,70),"2026-07","S1","M1")["forecast_towell"][0]["probability"]
        self.assertLessEqual(row["p10"],row["p50"]); self.assertLessEqual(row["p50"],row["p90"]); self.assertLessEqual(row["p90"],row["p95"])
        self.assertNotEqual(row["p90"],row["p50"]*1.2)

    def test_cp14_insufficient_data_preserves_prior(self):
        result=select_strategy(records(90,70,windows=1),EnsembleConfig(minimum_windows=3))
        self.assertIsNone(result["challenger"])

    def test_cp15_worse_challenger_never_publishes(self):
        result=run_ensemble(records(95,70),future(95,70),"2026-07","S1","M1")
        self.assertFalse(result["publication"]["automatic_promotion"]); self.assertEqual(result["selection"]["official"]["strategy"],"statistical")

    def test_cp16_normalized_contract_never_excel(self):
        result=run_ensemble(records(90,70),future(),"2026-07","S1","M1")
        self.assertEqual(result["source"],"normalized_platform_records"); self.assertFalse(result["excel_required"])

    def test_cp17_to_cp20_visual_scope_has_baseline(self):
        baseline=Path(__file__).with_name("visual-baseline.json")
        self.assertTrue(baseline.exists())


if __name__ == "__main__": unittest.main()
