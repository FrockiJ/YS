import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipelines.llm.openai_client import OpenAIChatHTTPError
from src.services.ai.generation import GenerationService


class GenerationServiceErrorTests(unittest.TestCase):
    def test_unauthorized_model_error_is_a_safe_service_configuration_message(self):
        service = GenerationService()
        metadata = service._generation_failure_metadata(
            OpenAIChatHTTPError(status=401, model="gpt-5.5", body='{"error":"secret detail"}'),
            language="zh-TW",
        )

        self.assertTrue(metadata["model_access_denied"])
        self.assertEqual(metadata["generation_error_status"], 401)
        self.assertNotIn("secret detail", str(metadata))
        self.assertNotIn("把問題縮小", service._build_generation_failure_text(metadata, "zh-TW"))


if __name__ == "__main__":
    unittest.main()
