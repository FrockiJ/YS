import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipelines.extract.quality import assess_text_quality, merge_quality_metadata


class QualityHeuristicTests(unittest.TestCase):
    def test_marks_mojibake_like_text_as_garbled(self):
        payload = assess_text_quality("擐玟 ?? ??? ??? \ufffd \ufffd official")
        self.assertTrue(payload["is_garbled"])
        self.assertLess(payload["encoding_quality"], 0.9)

    def test_keeps_normal_chinese_text_readable(self):
        payload = assess_text_quality("請推薦 5 支適合商務送禮的香檳，預算 3000 到 5000，優先現貨。")
        self.assertFalse(payload["is_garbled"])
        self.assertGreater(payload["content_quality"], 0.35)

    def test_merge_quality_metadata_preserves_existing_meta(self):
        meta = merge_quality_metadata({"brand": "TrailForge"}, "TrailForge official product profile.")
        self.assertEqual(meta["brand"], "TrailForge")
        self.assertIn("content_quality", meta)
        self.assertIn("encoding_quality", meta)
        self.assertIn("is_garbled", meta)


if __name__ == "__main__":
    unittest.main()
