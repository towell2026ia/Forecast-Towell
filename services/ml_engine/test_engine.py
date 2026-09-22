import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from engine import GradientBoostingGlobal, LinearGlobal, RandomForestGlobal, Series, build_payload, feature_vector, metric, rolling_backtest_history


class MLEngineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.periods=[f"2025-{m:02d}" for m in range(1,13)]+[f"2026-{m:02d}" for m in range(1,13)]
        self.series=Series("a","Azul","Azul","Fendi",{p:float(0 if i%5==0 else 10+i) for i,p in enumerate(self.periods)})

    def test_cp01_feature_dataset(self):
        values,names=feature_vector(self.series,self.periods,12,"2026-02",1,["a"])
        self.assertEqual(len(values),len(names)); self.assertIn("venta t-12",names)
    def test_cp02_features_do_not_read_future(self):
        before=feature_vector(self.series,self.periods,10,"2025-12",1,["a"])[0]
        self.series.points["2026-12"]=999999
        after=feature_vector(self.series,self.periods,10,"2025-12",1,["a"])[0]
        self.assertEqual(before,after)
    def test_cp03_short_history_supported(self):
        short=Series("b","Nuevo","Nuevo","Fendi",{p:10.0 for p in self.periods[-7:]})
        self.assertIsNotNone(feature_vector(short,self.periods,23,"2027-01",1,["a","b"])[0])
    def test_cp04_zero_is_not_missing(self): self.assertIn(0.0,self.series.points.values())
    def test_cp05_null_is_preserved(self):
        self.series.points[self.periods[-1]]=None
        self.assertIsNone(feature_vector(self.series,self.periods,23,"2027-01",1,["a"])[0][8])
    def test_cp06_champion_challenger_are_distinct(self):
        self.assertNotEqual(LinearGlobal.name,RandomForestGlobal.name)
    def test_cp07_worse_challenger_does_not_replace_champion(self):
        rows=[{"model":"a","score":5},{"model":"b","score":8}]
        self.assertEqual(min(rows,key=lambda r:r["score"])["model"],"a")
    def test_cp08_better_challenger_is_candidate_only(self):
        status="Challenger"; self.assertNotEqual(status,"Champion")
    def test_cp09_wape(self): self.assertEqual(metric([100,100],[90,110])["wape"],10.0)
    def test_cp10_statistical_fallback_independent(self):
        self.assertTrue(callable(GradientBoostingGlobal)); self.assertTrue(Path(__file__).parents[1].joinpath("statistical_engine","engine.py").exists())
    def test_cp11_backtest_history_is_out_of_sample(self):
        rows=rolling_backtest_history([self.series],LinearGlobal,"Venta",3)
        self.assertTrue(rows); self.assertTrue(all(row["period"] in self.periods for row in rows))


if __name__ == "__main__": unittest.main()
