from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.assistant_api.availability import AvailabilityRuleRegistry, TemporalAvailabilityAuditor
from services.assistant_api.test_historical_runner import MemoryProvider, next_month


def row(period: str, objective: str = "Venta", value: str = "100", **extra: str) -> dict[str, str]:
    return {"chain": "Walmart", "pilot_scope": "FENDI BD", "canonical_product_id": "sku-1",
            "objective": objective, "period": period, "value": value, "is_missing": "False",
            "close_status": "closed", **extra}


class AvailabilityTests(unittest.TestCase):
    def auditor(self, rows: list[dict[str, str]], directory: str,
                evidence: dict | None = None) -> TemporalAvailabilityAuditor:
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(evidence or {}), encoding="utf-8")
        return TemporalAvailabilityAuditor(MemoryProvider(rows), Path(directory) / "state",
                                           AvailabilityRuleRegistry(path))

    def test_direct_timestamp_cutoff_and_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            known = row("2025-01", available_at="2025-03-01",
                        availability_source="system_timestamp", availability_confidence="verified")
            unknown = row("2025-01", objective="Pedido", available_at="2025-01-01")
            auditor = self.auditor([known, unknown], directory)
            before = auditor.gate("2025-02", "2025-02-28")
            self.assertEqual(before["exclusion_reasons"], {"available_after_cutoff": 1,
                                                           "availability_unknown": 1})
            after = auditor.gate("2025-03", "2025-03-31")
            self.assertEqual([item["value"] for item in after["rows"]], ["100"])

    def test_monthly_closure_and_documented_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = {"monthly_closures": [{"period": "2025-01", "closure_status": "CLOSED",
                        "closed_at": "2025-02-02", "closure_source": "monthly_closure",
                        "rule_id": "SALE_CLOSE_V1", "evidence_reference": "closure-log-1"}],
                        "rules": [{"rule_id": "ORDER_RULE_V1", "enabled": True,
                                   "available_at": "2025-01-15", "availability_source": "business_rule",
                                   "availability_confidence": "documented",
                                   "evidence_reference": "approved order policy"}]}
            sale = row("2025-01")
            order = row("2025-01", "Pedido", available_at="2025-01-15",
                        availability_source="business_rule", availability_confidence="documented",
                        availability_rule_id="ORDER_RULE_V1")
            auditor = self.auditor([sale, order], directory, evidence)
            self.assertEqual([item["objective"] for item in auditor.gate("2025-01", "2025-01-31")["rows"]],
                             ["Pedido"])
            later = auditor.gate("2025-02", "2025-02-03")["rows"]
            self.assertEqual(len(later), 2)
            self.assertEqual(next(item for item in later if item["objective"] == "Venta")
                             ["availability_confidence"], "documented")

    def test_inferred_manual_without_evidence_and_unknown_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [row("2025-01", available_at="2025-02-01", availability_source="business_rule",
                        availability_confidence="inferred"),
                    row("2025-02", available_at="2025-03-01", availability_source="manual_verified",
                        availability_confidence="verified"), row("2025-03")]
            result = self.auditor(rows, directory).gate("2025-04", "2025-04-30")
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["exclusion_reasons"], {"inferred_rejected": 1,
                                                          "availability_unknown": 2})

    def test_forecast_received_before_target_and_order_independent_of_sales(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [row("2025-12", "Fcst Cliente", forecast_received_at="2025-08-15"),
                    row("2025-08", "Pedido", order_created_at="2025-08-10"),
                    row("2025-08", "Venta", closed_at="2025-09-02")]
            result = self.auditor(rows, directory).gate("2025-08", "2025-08-31")
            self.assertEqual(len(result["known_future"]), 1)
            self.assertEqual(result["known_future"][0]["available_at"][:10], "2025-08-15")
            self.assertEqual([item["objective"] for item in result["rows"]], ["Pedido"])
            self.assertEqual(result["exclusion_reasons"], {"available_after_cutoff": 1})

    def test_manual_verification_requires_evidence_and_can_be_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            verified = row("2025-01", available_at="2025-02-05",
                           availability_source="manual_verified", availability_confidence="verified",
                           verification_method="signed_closure_log", verified_by="authorized_manager",
                           verification_notes="Matches archived January closure",
                           evidence_reference="archive:closure-jan-2025")
            result = self.auditor([verified], directory).gate("2025-02", "2025-02-28")
            self.assertEqual(len(result["rows"]), 1)

    def test_correction_versions_and_chain_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            original = row("2025-01", "Venta", "100", available_at="2025-02-02",
                           availability_source="system_timestamp", availability_confidence="verified",
                           data_version="1")
            corrected = row("2025-01", "Venta", "126", available_at="2025-02-10",
                            availability_source="system_timestamp", availability_confidence="verified",
                            data_version="2")
            other_chain = row("2025-01", "Pedido", "50", available_at="2025-02-02",
                              availability_source="system_timestamp", availability_confidence="verified")
            other_chain["chain"] = "Unknown"
            auditor = self.auditor([original, corrected, other_chain], directory)
            self.assertEqual(auditor.gate("2025-02", "2025-02-05")["rows"][0]["value"], "100")
            later = auditor.gate("2025-02", "2025-02-15")
            self.assertEqual([item["value"] for item in later["rows"]], ["126"])
            self.assertEqual(later["exclusion_reasons"], {"superseded_as_of_cutoff": 1,
                                                         "chain_unverified": 1})

    def test_required_sales_blocks_but_optional_missing_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [row(next_month("2025-01", index), available_at="2025-08-01",
                        availability_source="system_timestamp", availability_confidence="verified")
                    for index in range(7)]
            auditor = self.auditor(rows, directory)
            self.assertEqual(auditor.validate_temporal_readiness("2025-07", cutoff="2025-07-31")
                             ["status"], "BLOCKED_AVAILABILITY")
            result = auditor.validate_temporal_readiness("2025-08", cutoff="2025-08-02")
            self.assertTrue(result["ready"])
            self.assertEqual(result["status"], "READY_WITH_WARNINGS")
            self.assertEqual(result["consecutive_active_periods"], 7)

    def test_backfill_dry_run_source_verification_and_audit_trail(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "snapshot.xlsx"
            source.write_bytes(b"source bytes under test")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            evidence = {"rules": [{"rule_id": "SOURCE_TEST_V1", "enabled": True,
                        "source_file": source.name, "sha256": digest,
                        "source_modified_at": "2025-01-31T00:00:00Z",
                        "local_created_at": "2025-02-02T00:00:00Z",
                        "local_last_write_at": "2025-02-02T00:00:00Z",
                        "available_at": "2025-02-02T00:00:00Z",
                        "availability_source": "source_file_timestamp",
                        "availability_confidence": "verified", "through_period": "2025-01",
                        "chain": "Walmart", "pilot_scope": "FENDI BD", "closure_status": "CLOSED",
                        "evidence_reference": "test source digest and cell"}]}
            rows = [row("2025-01", record_hash="r1", source_file=source.name,
                        source_sheet="Base", source_cell="A1")]
            auditor = self.auditor(rows, directory, evidence)
            with patch("services.assistant_api.availability._source_cells", return_value={"A1": 100.0}):
                preview = auditor.backfill_availability(Path(directory), dry_run=True)
                self.assertEqual(preview["new_assignments"], 1)
                self.assertFalse(auditor.assignments_path.exists())
                applied = auditor.backfill_availability(Path(directory), dry_run=False)
                self.assertEqual(applied["assigned_records"], 1)
                self.assertEqual(len(json.loads(auditor.trail_path.read_text())), 1)
                self.assertEqual(auditor.backfill_availability(Path(directory), dry_run=False)
                                 ["new_assignments"], 0)
                auditor.registry.rules["SOURCE_TEST_V1"]["enabled"] = False
                self.assertEqual(auditor.gate("2025-02", "2025-02-28")["exclusion_reasons"],
                                 {"availability_unknown": 1})
                auditor.registry.rules["SOURCE_TEST_V1"]["enabled"] = True
            with patch("services.assistant_api.availability._source_cells", return_value={"A1": 99.0}):
                with self.assertRaisesRegex(ValueError, "normalized_source_cell_mismatch"):
                    auditor.backfill_availability(Path(directory))


if __name__ == "__main__":
    unittest.main()
