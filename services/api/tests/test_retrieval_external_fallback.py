import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.schemas.ai import Hit
from src.services.ai.retrieval import RetrievalService


class RetrievalExternalFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_is_not_attempted_for_stable_knowledge(self):
        external = Mock()
        service = RetrievalService(external)
        with patch(
            "src.services.ai.retrieval.rag_corpus_status",
            new=AsyncMock(return_value={"status": "empty_corpus", "row_count": 0}),
        ):
            result = await service.search("學習方法", conn=object())
        self.assertFalse(result.external_search["attempted"])
        external.search.assert_not_called()

    async def test_external_is_attempted_only_after_required_rag_miss(self):
        external = Mock()
        external.search.return_value = ([], {}, {"attempted": True, "provider_unavailable": True})
        service = RetrievalService(external)
        with patch(
            "src.services.ai.retrieval.rag_corpus_status",
            new=AsyncMock(return_value={"status": "empty_corpus", "row_count": 0}),
        ):
            result = await service.search(
                "玉山天氣",
                conn=object(),
                needs_authoritative_sources=True,
                external_search_reason="live_weather",
                external_query="玉山目前天氣",
            )
        self.assertTrue(result.external_search["attempted"])
        self.assertTrue(result.external_search["provider_unavailable"])
        self.assertEqual(external.search.call_args.args[0], "玉山目前天氣")

    async def test_external_is_skipped_when_rag_has_qualified_evidence(self):
        external = Mock()
        service = RetrievalService(external)
        row = {
            "id": "rag:1",
            "text": "已核准的內部資料",
            "summary": "已核准的內部資料",
            "score": 0.9,
            "meta": {},
        }
        with patch(
            "src.services.ai.retrieval.rag_corpus_status",
            new=AsyncMock(return_value={"status": "ready", "row_count": 1}),
        ), patch.object(service, "_search_variants", new=AsyncMock(return_value=[row])):
            result = await service.search(
                "查證規範",
                conn=object(),
                needs_authoritative_sources=True,
                external_search_reason="regulation",
            )
        self.assertEqual(result.retrieval_snapshot["rag_status"], "used")
        self.assertFalse(result.external_search["attempted"])
        external.search.assert_not_called()


if __name__ == "__main__":
    unittest.main()

