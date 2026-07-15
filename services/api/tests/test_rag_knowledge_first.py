import unittest
from unittest.mock import patch

from src.pipelines.nlp.embedder import EmbeddingUnavailableError
from src.pipelines.rag import searcher


class FakeConnection:
    def __init__(self, status_row, rows=None):
        self.status_row = status_row
        self.rows = list(rows or [])
        self.fetch_calls = []

    async def fetchrow(self, *_args):
        return self.status_row

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self.rows


class RagKnowledgeFirstTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_corpus_does_not_call_embedding(self):
        connection = FakeConnection({"row_count": 0, "min_dim": None, "max_dim": None})
        with patch.object(searcher, "embed_texts") as embed:
            rows = await searcher.vector_search(connection, "玉山雨季")

        self.assertEqual(rows, [])
        embed.assert_not_called()

    async def test_vector_query_uses_configured_relevance_threshold(self):
        connection = FakeConnection({"row_count": 1, "min_dim": 384, "max_dim": 384})
        fake_vector = type("Vector", (), {"tolist": lambda self: [0.0] * 384})()
        with patch.object(searcher, "embed_texts", return_value=[fake_vector]):
            await searcher.vector_search(connection, "登山防水", k=20)

        self.assertEqual(len(connection.fetch_calls), 1)
        sql, args = connection.fetch_calls[0]
        self.assertIn("1 - (embedding <=> $1::vector) >= $4", sql)
        self.assertEqual(args[1], 20)
        self.assertEqual(args[3], searcher.RAG_MIN_SCORE)

    async def test_embedding_failure_has_no_broad_text_fallback(self):
        connection = FakeConnection({"row_count": 1, "min_dim": 384, "max_dim": 384})
        with patch.object(
            searcher,
            "embed_texts",
            side_effect=EmbeddingUnavailableError("offline", model="test"),
        ):
            rows = await searcher.vector_search(connection, "解釋牛頓第二運動定律")

        self.assertEqual(rows, [])
        self.assertEqual(connection.fetch_calls, [])

    async def test_dimension_mismatch_is_reported_as_error(self):
        connection = FakeConnection({"row_count": 3, "min_dim": 1536, "max_dim": 1536})

        status = await searcher.rag_corpus_status(connection)

        self.assertEqual(status["status"], "error")
        self.assertEqual(status["error"], "embedding_dimension_mismatch")


if __name__ == "__main__":
    unittest.main()
