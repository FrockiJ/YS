import json
import unittest
from unittest.mock import AsyncMock, patch

from src.pipelines.llm.openai_client import ChatCompletionResult, LLMRequestBudget
from src.services.ai.chat_planner import ChatPlanningService


def _result(payload):
    return ChatCompletionResult(
        content=json.dumps(payload, ensure_ascii=False),
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        model="test-model",
    )


class ChatPlanningServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stable_knowledge_uses_free_answer_without_external(self):
        payload = {
            "version": "2",
            "task_type": "knowledge",
            "answer_mode": "knowledge_only",
            "rag_queries": ["如何制定學習計畫"],
            "external": {"required": False},
            "confidence": 0.97,
        }
        budget = LLMRequestBudget()
        with patch(
            "src.services.ai.chat_planner.chat_complete_result",
            new=AsyncMock(return_value=_result(payload)),
        ):
            plan = await ChatPlanningService().plan("推薦一種學習方法", budget=budget)
        self.assertEqual(plan.task_type, "knowledge")
        self.assertFalse(plan.external.required)
        self.assertIsNone(plan.erp_ast)

    async def test_mixed_prompt_returns_traceable_fuzzy_erp_ast(self):
        payload = {
            "version": "2",
            "task_type": "mixed",
            "answer_mode": "mixed",
            "rag_queries": ["玉山雨季登山準備"],
            "external": {"required": False},
            "erp_ast": {
                "version": "2",
                "operation": "recommendation",
                "projections": ["sku", "name", "specification", "price", "stock"],
                "search_terms": [
                    {
                        "value": "防水登山裝備",
                        "match": "fuzzy",
                        "fields": ["name", "category", "specification"],
                        "source_trace": {
                            "source": "llm_inference",
                            "reference": "雨季登山需要防水功能",
                        },
                    }
                ],
                "predicates": [
                    {
                        "field": "price",
                        "operator": "lte",
                        "value": 3000,
                        "source_trace": {
                            "source": "current_message",
                            "reference": "3000 元內",
                        },
                    },
                    {
                        "field": "stock",
                        "operator": "gte",
                        "value": 1,
                        "source_trace": {
                            "source": "current_message",
                            "reference": "有庫存",
                        },
                    },
                ],
                "limit": 20,
            },
            "confidence": 0.94,
        }
        with patch(
            "src.services.ai.chat_planner.chat_complete_result",
            new=AsyncMock(return_value=_result(payload)),
        ):
            plan = await ChatPlanningService().plan(
                "玉山雨季怎麼準備，順便推薦有庫存且 3000 元內的裝備",
                budget=LLMRequestBudget(),
            )
        self.assertEqual(plan.answer_mode, "mixed")
        self.assertEqual(plan.erp_ast.limit, 6)
        self.assertEqual(plan.erp_ast.search_terms[0].match, "fuzzy")
        self.assertEqual(plan.erp_ast.predicates[0].value, 3000)

    async def test_external_is_semantic_plan_data_not_runtime_keyword_route(self):
        payload = {
            "version": "2",
            "task_type": "knowledge",
            "answer_mode": "knowledge_only",
            "rag_queries": ["玉山天氣"],
            "external": {
                "required": True,
                "query": "玉山目前天氣",
                "reason": "live_weather",
            },
            "confidence": 0.98,
        }
        with patch(
            "src.services.ai.chat_planner.chat_complete_result",
            new=AsyncMock(return_value=_result(payload)),
        ):
            plan = await ChatPlanningService().plan("玉山天氣如何", budget=LLMRequestBudget())
        self.assertTrue(plan.external.required)
        self.assertEqual(plan.external.reason, "live_weather")

    async def test_external_query_normalizes_inconsistent_required_flag(self):
        payload = {
            "version": "2",
            "task_type": "knowledge",
            "answer_mode": "knowledge_only",
            "rag_queries": ["mountain weather"],
            "external": {
                "required": False,
                "query": "current mountain weather",
                "reason": "live weather requires current evidence",
            },
            "confidence": 0.95,
        }
        with patch(
            "src.services.ai.chat_planner.chat_complete_result",
            new=AsyncMock(return_value=_result(payload)),
        ):
            plan = await ChatPlanningService().plan(
                "Please check the mountain weather now",
                budget=LLMRequestBudget(),
            )
        self.assertTrue(plan.external.required)
        self.assertTrue(plan.audit_metadata()["external_required"])

    async def test_destination_plan_keeps_departure_and_destination_facts_separate(self):
        payload = {
            "version": "2",
            "task_type": "destination",
            "answer_mode": "knowledge_only",
            "rag_queries": ["three-day mountain campsite planning"],
            "external": {"required": False},
            "trip_plan_patch": {
                "activity": "camping",
                "destination_region": "southern Taiwan",
                "departure_location": "Kaohsiung",
                "elevation_band": "mid elevation",
                "duration_days": 3,
            },
            "confidence": 0.96,
        }
        with patch(
            "src.services.ai.chat_planner.chat_complete_result",
            new=AsyncMock(return_value=_result(payload)),
        ):
            plan = await ChatPlanningService().plan(
                "Filter the three-day campsites from Kaohsiung",
                budget=LLMRequestBudget(),
            )
        self.assertEqual(plan.trip_plan_patch.departure_location, "Kaohsiung")
        self.assertEqual(plan.trip_plan_patch.destination_region, "southern Taiwan")
        self.assertEqual(plan.trip_plan_patch.duration_days, 3)

    def test_planner_failure_fallback_never_promotes_to_erp(self):
        plan = ChatPlanningService.fallback("未知混合問題")
        self.assertEqual(plan.answer_mode, "knowledge_only")
        self.assertIsNone(plan.erp_ast)
        self.assertFalse(plan.external.required)


if __name__ == "__main__":
    unittest.main()
