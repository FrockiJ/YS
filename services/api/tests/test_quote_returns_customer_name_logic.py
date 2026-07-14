import ast
import unittest
import uuid
from pathlib import Path


def _load_quote_return_helpers():
    path = Path(__file__).resolve().parents[1] / "src" / "api" / "routes_quotes.py"
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    needed = {
        "_normalize_quote_customer_name",
        "_resolve_quote_customer_name_from_conversation",
        "_resolve_quote_customer_name",
    }
    segments = [
        "from typing import Any, Optional\nfrom uuid import UUID\n",
        """
class AsyncSession:
    pass

class _Expr:
    def where(self, *args, **kwargs):
        return self

def select(*args, **kwargs):
    return _Expr()

class _Column:
    def __eq__(self, other):
        return ("eq", other)

class Conversation:
    id = _Column()
""",
    ]
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name in needed:
            segments.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.AsyncFunctionDef) and node.name in needed:
            segments.append(ast.get_source_segment(source, node))
    namespace = {}
    exec("\n\n".join(segments), namespace)
    return namespace


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        value = self._responses.pop(0) if self._responses else None
        return _ScalarResult(value)


class QuoteReturnCustomerNameLogicTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        namespace = _load_quote_return_helpers()
        cls.resolve_from_conversation = staticmethod(
            namespace["_resolve_quote_customer_name_from_conversation"]
        )
        cls.resolve_customer_name = staticmethod(namespace["_resolve_quote_customer_name"])

    def test_project_label_has_priority_over_title(self):
        conversation = type(
            "ConversationRow",
            (),
            {"project_label": "Folder Alpha", "title": "Fallback Title"},
        )()

        result = self.resolve_from_conversation(conversation, "Legacy Customer")

        self.assertEqual(result, "Folder Alpha")

    def test_title_is_used_when_project_label_is_blank(self):
        conversation = type(
            "ConversationRow",
            (),
            {"project_label": "   ", "title": "Conversation Title"},
        )()

        result = self.resolve_from_conversation(conversation, "Legacy Customer")

        self.assertEqual(result, "Conversation Title")

    def test_fallback_is_used_when_conversation_has_no_folder_name(self):
        conversation = type(
            "ConversationRow",
            (),
            {"project_label": "", "title": ""},
        )()

        result = self.resolve_from_conversation(conversation, "Legacy Customer")

        self.assertEqual(result, "Legacy Customer")

    async def test_async_helper_uses_conversation_folder_name(self):
        conversation = type(
            "ConversationRow",
            (),
            {"project_label": "Folder Beta", "title": "Conversation Title"},
        )()
        session = _FakeSession([conversation])

        result = await self.resolve_customer_name(
            session,
            str(uuid.uuid4()),
            "Legacy Customer",
        )

        self.assertEqual(result, "Folder Beta")
        self.assertEqual(session.calls, 1)

    async def test_async_helper_uses_fallback_for_invalid_conversation_id(self):
        session = _FakeSession([])

        result = await self.resolve_customer_name(session, "not-a-uuid", "Legacy Customer")

        self.assertEqual(result, "Legacy Customer")
        self.assertEqual(session.calls, 0)

    async def test_async_helper_uses_fallback_when_conversation_is_missing(self):
        session = _FakeSession([None])

        result = await self.resolve_customer_name(
            session,
            str(uuid.uuid4()),
            "Legacy Customer",
        )

        self.assertEqual(result, "Legacy Customer")
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
