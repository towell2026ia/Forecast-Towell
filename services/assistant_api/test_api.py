from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from services.assistant_api.api import create_app
from services.assistant_api.data_provider import NormalizedDataProvider
from services.assistant_api.orchestrator import ForecastOrchestrator, LocalIntentRouter
from services.assistant_api.tools import ForecastTools


class AssistantApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(NormalizedDataProvider()))
        cls.headers = {"x-actor-id": "local-manager"}

    def ask(self, message: str, context: dict | None = None):
        response = self.client.post("/api/assistant/message",
                                    json={"message": message, "context": context or {}},
                                    headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_health_and_real_champion(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        result = self.ask("¿Cuál es el Champion?")
        self.assertEqual(result["intent"], "champion_status")
        self.assertEqual(result["data"]["motor"], "ml")
        self.assertEqual(result["data"]["wape"], 12.3678)
        self.assertEqual(result["metadata"]["executed_command"], False)

    def test_historical_read_endpoints_are_protected_and_available(self):
        self.assertEqual(self.client.get("/api/historical/availability/audit").status_code, 403)
        audit = self.client.get("/api/historical/availability/audit",
                                params={"start_period": "2023-01", "end_period": "2026-08"},
                                headers=self.headers)
        self.assertEqual(audit.status_code, 200, audit.text)
        self.assertEqual(audit.json()["periods_audited"], 44)
        readiness = self.client.get("/api/historical/readiness/2026-08", headers=self.headers)
        self.assertEqual(readiness.status_code, 200)
        self.assertIn("blocking_fields", readiness.json())
        first = self.client.get("/api/historical/first-valid-period", headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertIn("first_valid_period", first.json())
        self.assertEqual(self.client.post("/api/historical/first-vintage").status_code, 403)

    def test_forecast_wape_fill_rate_and_bands(self):
        forecast = self.ask("Dame el forecast de 12 meses.")
        self.assertEqual(len(forecast["data"]["horizons"]), 12)
        self.assertEqual(forecast["data"]["horizons"][0]["forecast_towell"], 98192.64)
        wape = self.ask("Dame el WAPE.")
        self.assertEqual(wape["data"]["forecast_towell"], 12.3678)
        fill = self.ask("¿Cómo está el Fill Rate?", {"period": "2026-09"})
        self.assertEqual(fill["data"]["period"], "2026-07")
        self.assertAlmostEqual(fill["data"]["fill_rate"], 97.4079, places=2)
        bands = self.ask("Muéstrame P90.")
        self.assertGreater(bands["data"]["p90"], bands["data"]["p50"])

    def test_explicit_product_overrides_filter(self):
        result = self.ask("Dame el WAPE de Azul", {"product": "Gris"})
        self.assertEqual(result["data"]["product"], "Azul")
        self.assertEqual(result["data"]["statistical"], 21.66)
        filtered = self.ask("Dame el WAPE", {"product": "Gris"})
        self.assertEqual(filtered["data"]["product"], "Gris")
        self.assertEqual(filtered["data"]["statistical"], 31.71)

    def test_unknown_and_missing_are_not_fabricated(self):
        unknown = self.ask("¿Qué equipo de fútbol va a ganar?")
        self.assertEqual(unknown["status"], "unrecognized")
        self.assertEqual(unknown["data"], {})
        vintage = self.ask("¿Qué pronosticábamos en junio de 2025 para diciembre de 2025?")
        self.assertEqual(vintage["intent"], "forecast_vintage")
        self.assertFalse(vintage["data"]["available"])
        fva = self.ask("¿Mejoraron los ajustes humanos el FVA?")
        self.assertFalse(fva["data"]["available"])

    def test_backend_ignores_claimed_role(self):
        response = self.client.post("/api/assistant/message",
                                    json={"message": "Dame WAPE", "context": {"role": "manager"}},
                                    headers={"x-actor-id": "reader"})
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/api/models/champion", headers={"x-actor-id": "reader"})
        self.assertEqual(response.status_code, 403)

    def test_whitelist_and_provider_contract(self):
        orchestrator = ForecastOrchestrator(NormalizedDataProvider())
        with self.assertRaises(ValueError):
            orchestrator.query("__import__", {})
        self.assertEqual(orchestrator.provider.name, "normalized")
        self.assertEqual(LocalIntentRouter().route("Dame el WAPE")[0], "wape_summary")
        self.assertEqual(self.client.get("/api/models/drift", headers=self.headers).json()["state"], "stable")

    def test_vintage_months_inherit_context_year(self):
        intent, query = LocalIntentRouter().route(
            "¿Qué pronosticábamos en junio para diciembre?", {"period": "2026-09"}
        )
        self.assertEqual(intent, "forecast_vintage")
        self.assertEqual(query["issue_period"], "2026-06")
        self.assertEqual(query["target_period"], "2026-12")

    def test_operational_vintage_decision_and_fva(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "vintages.json").write_text(json.dumps([{
                "issue_period": "2026-07", "target_period": "2026-12",
                "series_id": "total-fendi-bd", "forecast_towell": 114859.84
            }]), encoding="utf-8")
            (state / "decisions.json").write_text(json.dumps([{
                "decision": {"target_period": "2026-11", "decision_version": "D1",
                             "entries": [{"series_id": "7501897813122", "horizon": 1,
                                          "forecast_towell": 10000, "adjustment": 1500,
                                          "forecast_approved": 11500, "reason": "promotion"}]},
                "evaluation": {"towell_wape": 6.7, "approved_wape": 1.0,
                               "details": [{"series_id": "7501897813122", "horizon": 1, "actual": 11300}]}
            }]), encoding="utf-8")
            tools = ForecastTools(NormalizedDataProvider(state_dir=state))
            vintage = tools.get_forecast_vintage({"issue_period": "2026-07", "target_period": "2026-12"})
            self.assertTrue(vintage["available"])
            history = tools.get_decision_history({"period": "2026-11"})
            self.assertEqual(history["decisions"][0]["actual"], 11300)
            self.assertEqual(history["decisions"][0]["forecast_approved"], 11500)
            fva = tools.get_fva_summary({})
            self.assertEqual(fva["classification"], "mejora")


if __name__ == "__main__":
    unittest.main()
