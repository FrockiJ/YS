import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.i18n import t
from src.pipelines.compose import composer


class LlmWithoutRagTests(unittest.TestCase):
    def _compose(self, *, prompt_category):
        captured = {}
        conversation_id = uuid.uuid4()
        assistant_id = uuid.uuid4()

        async def fake_complete(**kwargs):
            captured.update(kwargs)
            return "可依模型知識回答。"

        async def fake_add_message(current_conversation_id, role, content, **kwargs):
            if kwargs.get("return_message_id"):
                captured["assistant_metadata"] = kwargs.get("metadata")
                return conversation_id, assistant_id
            return conversation_id

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            with mock.patch.object(composer.openai_client, "chat_complete", side_effect=fake_complete):
                with mock.patch.object(composer, "add_message_to_conversation", side_effect=fake_add_message):
                    result = asyncio.run(
                        composer.compose_answer(
                            "台灣梨山一日遊的路線推薦",
                            [],
                            prompt_category=prompt_category,
                            lang="zh-TW",
                        )
                    )
        return result, captured

    def test_general_chat_without_rag_calls_llm_without_citations(self):
        result, captured = self._compose(prompt_category="general_chat")

        self.assertEqual(result["text"], "可依模型知識回答。")
        self.assertEqual(result["citations"], [])
        self.assertEqual(result["metadata"]["retrieval_mode"], "llm_without_rag")
        self.assertFalse(result["metadata"]["rag_used"])
        self.assertEqual(captured["assistant_metadata"], {"retrieval_mode": "llm_without_rag", "rag_used": False})
        self.assertIn(t("compose.no_rag_instruction", "zh-TW"), captured["system"])

    def test_non_general_category_keeps_its_existing_grounding_contract(self):
        result, captured = self._compose(prompt_category="source_validation")

        self.assertNotIn("retrieval_mode", result.get("metadata", {}))
        self.assertNotIn(t("compose.no_rag_instruction", "zh-TW"), captured["system"])


if __name__ == "__main__":
    unittest.main()
