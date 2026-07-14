import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import phase2_dataset as dataset
import phase3_submit_fine_tune_job as submit_job


class Phase3SubmitFineTuneJobTests(unittest.TestCase):
    def test_submit_refuses_when_readiness_gate_fails(self):
        rows = []
        for index, case_id in enumerate(sorted(dataset.HOLDOUT_CASE_IDS), start=1):
            rows.append(
                {
                    "id": index,
                    "query": f"Holdout {case_id}",
                    "selected_key": case_id,
                    "feedback_type": "uat_holdout",
                    "case_id": case_id,
                    "issue_tags": [],
                    "correction_text": "Holdout example.",
                    "preferred_answer": None,
                    "retrieval_snapshot": {"selected_hit_count": 1},
                    "answer_metadata_snapshot": {},
                    "review_status": "holdout_only",
                    "dataset_split": "holdout",
                }
            )

        class Args:
            model = "gpt-5-mini"
            suffix = "ys-phase3"
            timeout = 1.0

        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = Path(tmpdir)
            dataset.export_training_data(rows, export_dir)
            Args.export_dir = str(export_dir)
            result = submit_job.run(Args())

        self.assertFalse(result["submitted"])
        self.assertEqual(result["not_submitted"], "readiness_failed")
        self.assertIn("sft_train_minimum", result["validation_errors"][0])


if __name__ == "__main__":
    unittest.main()
