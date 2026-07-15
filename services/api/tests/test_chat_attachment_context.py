import unittest
from unittest.mock import AsyncMock, patch

from src.api.routes_chat import _load_recent_attachment_context


class ChatAttachmentContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalized_metadata_can_be_loaded_on_repeated_turns(self):
        messages = [
            {"role": "user", "metadata": "legacy-invalid"},
            {
                "role": "assistant",
                "metadata": {"attachment_context": {"summary": "saved attachment"}},
            },
        ]
        with patch(
            "src.api.routes_chat.get_messages_by_conversation",
            new=AsyncMock(return_value=messages),
        ) as mocked:
            conversation_id = "9f8353d1-cb46-47b8-b4e4-e7f05ff8012d"
            first = await _load_recent_attachment_context(conversation_id)
            second = await _load_recent_attachment_context(conversation_id)
        self.assertEqual(first["summary"], "saved attachment")
        self.assertEqual(second["summary"], "saved attachment")
        self.assertEqual(mocked.await_count, 2)

    async def test_history_failure_is_optional(self):
        with patch(
            "src.api.routes_chat.get_messages_by_conversation",
            new=AsyncMock(side_effect=RuntimeError("temporary db error")),
        ):
            result = await _load_recent_attachment_context(
                "9f8353d1-cb46-47b8-b4e4-e7f05ff8012d"
            )
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
