import os
import sys
import unittest
import urllib.error
import io
from unittest import mock
from pathlib import Path

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipelines.llm import openai_client


class OpenAIClientTests(unittest.TestCase):
    def test_model_resolution_uses_primary_and_fallback(self):
        with mock.patch.dict(
            os.environ,
            {"OPENAI_CHAT_MODEL": "gpt-5", "OPENAI_FALLBACK_CHAT_MODEL": "gpt-5.4-mini"},
            clear=False,
        ):
            primary, fallback = openai_client._resolve_models()
        self.assertEqual(primary, "gpt-5")
        self.assertEqual(fallback, "gpt-5.4-mini")

    def test_model_resolution_uses_fine_tuned_canary_with_base_fallback(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_LANE": "fine_tuned_canary",
                "OPENAI_CHAT_MODEL": "gpt-5.4-mini",
                "OPENAI_FALLBACK_CHAT_MODEL": "gpt-5.4-mini",
                "OPENAI_FINE_TUNED_CHAT_MODEL": "ft:gpt-5.4-mini:ys:phase3",
            },
            clear=False,
        ):
            primary, fallback = openai_client._resolve_models()
        self.assertEqual(primary, "ft:gpt-5.4-mini:ys:phase3")
        self.assertEqual(fallback, "gpt-5.4-mini")

    def test_model_resolution_stays_base_when_canary_model_is_missing(self):
        with mock.patch.dict(
            os.environ,
            {
                "AI_MODEL_LANE": "fine_tuned_canary",
                "OPENAI_CHAT_MODEL": "gpt-5.4-mini",
                "OPENAI_FALLBACK_CHAT_MODEL": "gpt-5.4-mini",
                "OPENAI_FINE_TUNED_CHAT_MODEL": "",
            },
            clear=False,
        ):
            primary, fallback = openai_client._resolve_models()
        self.assertEqual(primary, "gpt-5.4-mini")
        self.assertIsNone(fallback)

    def test_sync_chat_complete_retries_with_fallback_model(self):
        attempted_models = []

        def fake_request(payload):
            attempted_models.append(payload["model"])
            if payload["model"] == "gpt-5":
                raise urllib.error.HTTPError(
                    url="https://api.openai.com/v1/chat/completions",
                    code=403,
                    msg="model forbidden",
                    hdrs=None,
                    fp=None,
                )
            return "fallback ok"

        with mock.patch.dict(
            os.environ,
            {"OPENAI_CHAT_MODEL": "gpt-5", "OPENAI_FALLBACK_CHAT_MODEL": "gpt-5.4-mini"},
            clear=False,
        ):
            with mock.patch("src.pipelines.llm.openai_client._request_chat_completion", side_effect=fake_request):
                response = openai_client._sync_chat_complete("system", "user")

        self.assertEqual(response, "fallback ok")
        self.assertEqual(attempted_models, ["gpt-5", "gpt-5.4-mini"])

    def test_sync_chat_complete_preserves_http_error_metadata_without_fallback(self):
        body = b'{"error":{"message":"model_not_found"}}'

        def fake_request(payload):
            raise urllib.error.HTTPError(
                url="https://api.openai.com/v1/chat/completions",
                code=403,
                msg="model forbidden",
                hdrs=None,
                fp=io.BytesIO(body),
            )

        with mock.patch.dict(
            os.environ,
            {"OPENAI_CHAT_MODEL": "gpt-5.4-mini", "OPENAI_FALLBACK_CHAT_MODEL": "gpt-5.4-mini"},
            clear=False,
        ):
            with mock.patch("src.pipelines.llm.openai_client._request_chat_completion", side_effect=fake_request):
                with self.assertRaises(openai_client.OpenAIChatHTTPError) as ctx:
                    openai_client._sync_chat_complete("system", "user")

        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.model, "gpt-5.4-mini")
        self.assertIn("model_not_found", ctx.exception.body)


if __name__ == "__main__":
    unittest.main()
