import ast
import unittest
import uuid
from pathlib import Path


def _load_search_helpers():
    path = Path(__file__).resolve().parents[1] / "src" / "services" / "project_service.py"
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    needed = {
        "ensure_authenticated_user",
        "_is_sadmin",
        "_user_identifier",
        "_normalize_excerpt_text",
        "_truncate_excerpt_around_query",
        "_build_match_excerpt",
        "_conversation_public_access_clause",
        "can_read_conversation",
    }
    segments = [
        "import re\nimport uuid\nfrom typing import Any, Dict, List, Optional, Tuple\n",
        """
class AsyncSession:
    pass

class HTTPException(Exception):
    def __init__(self, status_code: int = 500, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

class _Expr:
    def where(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

def select(*args, **kwargs):
    return _Expr()

def and_(*args, **kwargs):
    return ("and", args)

def or_(*args, **kwargs):
    return ("or", args)

class _Column:
    def __eq__(self, other):
        return ("eq", other)

    def __ne__(self, other):
        return ("ne", other)

    def isnot(self, other):
        return ("isnot", other)

    def is_(self, other):
        return ("is", other)

class ConversationInvitation:
    id = _Column()
    conversation_id = _Column()
    status = _Column()
    invited_user_id = _Column()
    invited_email = _Column()

class Project:
    id = _Column()
    is_archived = _Column()

async def can_read_project(session, user, project):
    return getattr(project, "_can_read", False)
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

    async def execute(self, _statement):
        value = self._responses.pop(0) if self._responses else None
        return _ScalarResult(value)


class ConversationSearchLogicTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        namespace = _load_search_helpers()
        cls.build_match_excerpt = staticmethod(namespace["_build_match_excerpt"])
        cls.can_read_conversation = staticmethod(namespace["can_read_conversation"])

    def test_build_match_excerpt_prefers_matching_paragraph(self):
        content = "第一段沒有關鍵字。\n\n第二段提到 YS AI 搜尋結果，這段應該被擷取。"
        excerpt = self.build_match_excerpt(content, "YS AI", "備援摘要")
        self.assertIn("YS AI", excerpt)
        self.assertIn("第二段", excerpt)

    def test_build_match_excerpt_falls_back_to_summary(self):
        excerpt = self.build_match_excerpt("", "不存在", "這是備援摘要")
        self.assertEqual(excerpt, "這是備援摘要")

    async def test_can_read_conversation_allows_accepted_conversation_invitation(self):
        session = _FakeSession([1])
        conversation = {
            "id": str(uuid.uuid4()),
            "user_id": 99,
            "visibility": "private",
            "owner_role": "admin",
            "project_id": None,
        }
        user = {"id": 7, "username": "reader@example.com", "role": "admin"}

        allowed = await self.can_read_conversation(session, user, conversation)

        self.assertTrue(allowed)

    async def test_can_read_conversation_allows_readable_project_conversation(self):
        project = type("ProjectRow", (), {"_can_read": True})()
        session = _FakeSession([None, project])
        conversation = {
            "id": str(uuid.uuid4()),
            "user_id": 99,
            "visibility": "private",
            "owner_role": "admin",
            "project_id": "proj-1",
        }
        user = {"id": 7, "username": "reader@example.com", "role": "admin"}

        allowed = await self.can_read_conversation(session, user, conversation)

        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
