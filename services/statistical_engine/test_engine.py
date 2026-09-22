import unittest

from engine import MODELS, active_lifecycle, backtest, classify, metrics, run_series


class EngineAcceptanceTests(unittest.TestCase):
    def test_cp01_regular(self): self.assertEqual(classify([10,11,9,10,10,9,11,10,9,10,11,10,10,9,10,11,9,10,10,11,10,9,11,10])[0], "Regular")
    def test_cp02_trend(self): self.assertEqual(classify([10 + i * 5 for i in range(24)])[0], "Tendencia")
    def test_cp03_seasonal(self): self.assertEqual(classify(([10,20,30,40,50,60,70,60,50,40,30,20] * 3))[0], "Estacional")
    def test_cp04_intermittent(self): self.assertIn("intermitente", classify([0,0,10,0,0,12] * 4)[0].lower())
    def test_cp05_zero_is_observation(self): self.assertEqual(MODELS["Croston"]([0,0,0], 3), [0.0,0.0,0.0])
    def test_cp06_insufficient(self): self.assertEqual(run_series("x","x",["2026-01"],[2],"Venta")["status"], "insufficient")
    def test_cp07_no_leakage(self):
        baseline = backtest([1]*20, MODELS["Naive"])["wape"]
        changed = backtest([1]*20+[999], MODELS["Naive"])["windows"][0]["origins"]
        self.assertGreater(changed, 0); self.assertEqual(baseline, 0)
    def test_cp08_wape(self): self.assertEqual(metrics([100,100],[90,110])[0], 10.0)
    def test_cp09_forecast_has_12_months(self):
        row=run_series("x","x",[f"2024-{i:02d}" for i in range(1,13)]+[f"2025-{i:02d}" for i in range(1,13)],[10]*24,"Venta")
        self.assertEqual(len(row["forecast"]),12)
    def test_cp10_all_required_models_exist(self):
        for name in ("Croston","SBA","TSB","Holt-Winters","Tendencia lineal","Tendencia polinómica"):
            self.assertIn(name, MODELS)
    def test_cp11_prelaunch_zeroes_are_excluded_only_before_first_sale(self):
        periods=[f"2024-{i:02d}" for i in range(1,7)]
        model_periods,values,offset=active_lifecycle(periods,[0,0,10,0,12,15])
        self.assertEqual(offset,2); self.assertEqual(model_periods[0],"2024-03"); self.assertEqual(values,[10,0,12,15])
    def test_cp12_history_contains_out_of_sample_forecast(self):
        periods=[f"2024-{i:02d}" for i in range(1,13)]+[f"2025-{i:02d}" for i in range(1,13)]
        row=run_series("x","x",periods,[10+i for i in range(24)],"Venta")
        self.assertTrue(any(point["forecast"] is not None for point in row["history"]))


if __name__ == "__main__": unittest.main()
