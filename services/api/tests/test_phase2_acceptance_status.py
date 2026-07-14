import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook


def _load_acceptance_module():
    path = Path(__file__).resolve().parents[3] / "scripts" / "phase2_acceptance_status.py"
    spec = importlib.util.spec_from_file_location("phase2_acceptance_status", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


acceptance = _load_acceptance_module()


HEADERS = [
    "Case ID",
    "Source Scope",
    "Response Mode",
    "Answer Mode",
    "Hard Error Flags",
    "Unmapped Citation Count",
    "Followup Context Resolved",
    "Official Inventory Proof Count",
    "Auto Evaluation",
    "Failure Reason",
    "Answer Excerpt",
]


class Phase2AcceptanceStatusTests(unittest.TestCase):
    def _write_workbook(self, path: Path, rows):
        wb = Workbook()
        try:
            ws = wb.active
            ws.title = "Phase2_Testcase_20260420_5"
            ws.append(HEADERS)
            for row in rows:
                ws.append(row)
            wb.save(path)
        finally:
            wb.close()

    def test_acceptance_sheet_allows_only_non_blocking_missing_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "MKT-03",
                        "authoritative_external_required",
                        "templated_fail_closed",
                        "fail_closed",
                        "missing_source",
                        0,
                        True,
                        8,
                        "Pass Candidate",
                        "",
                        "fail closed",
                    ],
                    ["CUS-01", "internal_preferred", "", "", "", 0, None, 0, "Skipped", "blank prompt", ""],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=1,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["counts"], {"Pass Candidate": 1, "Skipped": 1})
            self.assertEqual(report["hard_error_counts"], {"missing_source": 1})
            self.assertEqual(report["blocking_hard_cases"], [])
            self.assertEqual(report["fail_closed_count"], 1)
            self.assertEqual(report["allowed_fail_closed_count"], 1)
            self.assertEqual(report["answerability_covered_count"], 1)
            self.assertEqual(report["generation_fallback_count"], 0)

    def test_acceptance_sheet_reports_blocking_hard_flags_and_failures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "MKT-06",
                        "authoritative_external_required",
                        "generated",
                        "generated",
                        "wrong_entity,missing_source",
                        0,
                        False,
                        0,
                        "Fail",
                        "bad entity",
                        "",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["counts"], {"Fail": 1})
            self.assertEqual(report["fail_cases"][0]["case_id"], "MKT-06")
            self.assertEqual(report["blocking_hard_cases"][0]["blocking_hard_error_flags"], ["wrong_entity"])

    def test_acceptance_sheet_rejects_generation_fallback_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "CUS-01",
                        "internal_preferred",
                        "generation_fallback",
                        "fail_closed",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "model request failed",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["generation_fallback_count"], 1)
            self.assertEqual(report["non_answer_pass_cases"][0]["case_id"], "CUS-01")

    def test_acceptance_sheet_rejects_unexpected_fail_closed_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "CUS-06",
                        "internal_preferred",
                        "templated_fail_closed",
                        "fail_closed",
                        "missing_source",
                        0,
                        True,
                        0,
                        "Pass Candidate",
                        "",
                        "I cannot verify this with authoritative sources, so I will not guess.",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["allowed_fail_closed_count"], 0)
            self.assertEqual(report["unexpected_fail_closed_pass_cases"][0]["case_id"], "CUS-06")

    def test_acceptance_sheet_allows_ranking_shortlist_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "CUS-TRQ-03",
                        "internal_preferred",
                        "templated_internal_low_coverage",
                        "ranking_shortlist",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "Shortlist: Mugneret-Gibourg, Hudelot-Noellat, Meo-Camuzet.",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["substantive_answer_count"], 1)
            self.assertEqual(report["non_answer_pass_cases"], [])

    def test_acceptance_sheet_allows_grounded_gap_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "TQ-02",
                        "internal_preferred",
                        "templated_internal_low_coverage",
                        "grounded_gap",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "The retrieved material does not contain enough passages that explicitly match the target vineyard.",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertTrue(report["ok"])
            self.assertEqual(report["non_answer_pass_cases"], [])

    def test_acceptance_sheet_rejects_pass_candidate_missing_answer_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            self._write_workbook(
                workbook,
                [
                    [
                        "TQ-01",
                        "internal_preferred",
                        "generated",
                        "",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "YS Trapet profile.",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=1,
                expected_skipped=0,
            )

            self.assertFalse(report["ok"])
            self.assertEqual(report["missing_answer_mode_cases"][0]["case_id"], "TQ-01")

    def test_acceptance_can_track_key_cases_from_fixture_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workbook = Path(tmpdir) / "acceptance.xlsx"
            fixture = Path(tmpdir) / "cases.json"
            fixture.write_text(
                json.dumps(
                    [{"case_id": "TQ-01"}, {"case_id": "TQ-02"}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self._write_workbook(
                workbook,
                [
                    [
                        "TQ-01",
                        "internal_preferred",
                        "generated",
                        "generated",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "YS Trapet profile.",
                    ],
                    [
                        "TQ-02",
                        "internal_preferred",
                        "generated",
                        "generated",
                        "",
                        0,
                        None,
                        0,
                        "Pass Candidate",
                        "",
                        "Clos Vougeot typicity.",
                    ],
                ],
            )

            report = acceptance.inspect_workbook_sheet(
                workbook,
                sheet_name="Phase2_Testcase_20260420_5",
                expected_pass=2,
                expected_skipped=0,
                key_case_ids=acceptance.load_case_fixture_ids(fixture),
            )

            self.assertTrue(report["ok"])
            self.assertEqual(set(report["key_cases"].keys()), {"TQ-01", "TQ-02"})

    def test_backup_inspection_reports_missing_acceptance_sheet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            backup = Path(tmpdir) / "backup.xlsx"
            wb = Workbook()
            try:
                wb.active.title = "Phase2_Testcase_20260420_4"
                wb.save(backup)
            finally:
                wb.close()

            report = acceptance.inspect_backup(backup, sheet_name="Phase2_Testcase_20260420_5")

            self.assertTrue(report["exists"])
            self.assertFalse(report["sheet_exists"])


if __name__ == "__main__":
    unittest.main()
