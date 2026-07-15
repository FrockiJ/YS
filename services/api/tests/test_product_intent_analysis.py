import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from src.services.ai.product_intent_analysis import (
    ProductIntentAnalysisService,
    ProductIntentPayload,
)


class StubIntentService(ProductIntentAnalysisService):
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def _classify_with_llm(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return ProductIntentPayload.model_validate(self.payload)


class ProductIntentAnalysisTests(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_prompt_marks_direct_equipment_request_as_immediate_erp(self):
        response = {
            "task_type": "product_recommendation",
            "decision": "erp_immediate",
            "confidence": 0.95,
            "need_profile_patch": {"activity": "hiking", "weather": ["rain"]},
        }
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch(
                "src.services.ai.product_intent_analysis.openai_client.chat_complete",
                new=AsyncMock(return_value=json.dumps(response)),
            ) as chat_complete:
                payload = await ProductIntentAnalysisService()._classify_with_llm(
                    "\u63a8\u85a6\u7389\u5c71\u96e8\u5b63\u88dd\u5099",
                    history=[],
                    context_state={},
                )

        self.assertEqual(payload.task_type, "product_recommendation")
        self.assertEqual(payload.decision, "erp_immediate")
        self.assertIn("推薦玉山雨季裝備", chat_complete.await_args.kwargs["system"])

    async def test_explicit_sku_stock_query_uses_rule(self):
        result = await ProductIntentAnalysisService().analyze("CAMP0001 有庫存嗎？")
        self.assertTrue(result.immediate)
        self.assertEqual(result.source, "rule")
        self.assertEqual(result.task_type, "erp_lookup")
        self.assertEqual(result.lookup_operation, "inventory_lookup")
        self.assertEqual(result.lookup_query, "CAMP0001")

    async def test_unknown_brand_stock_query_does_not_require_known_product_noun(self):
        result = await ProductIntentAnalysisService().analyze("bombada還有多少庫存")

        self.assertEqual(result.task_type, "erp_lookup")
        self.assertEqual(result.decision, "erp_immediate")
        self.assertEqual(result.lookup_operation, "inventory_lookup")
        self.assertEqual(result.lookup_query, "bombada")

    async def test_unknown_product_price_query_uses_traceable_subject(self):
        result = await ProductIntentAnalysisService().analyze("bombada價格是多少？")

        self.assertEqual(result.task_type, "erp_lookup")
        self.assertEqual(result.lookup_operation, "product_lookup")
        self.assertEqual(result.lookup_query, "bombada")

    async def test_english_inventory_question_extracts_only_traceable_subject(self):
        result = await ProductIntentAnalysisService().analyze("how much inventory does bombada have?")

        self.assertEqual(result.task_type, "erp_lookup")
        self.assertEqual(result.lookup_operation, "inventory_lookup")
        self.assertEqual(result.lookup_query, "bombada")

    async def test_subjectless_inventory_followup_uses_saved_erp_query(self):
        result = await ProductIntentAnalysisService().analyze(
            "還有庫存嗎？",
            history=[
                {
                    "role": "assistant",
                    "metadata": {
                        "erp_lookup": {"operation": "product_lookup", "query": "bombada"},
                        "product_results": [{"sku": "P355302935"}],
                    },
                }
            ],
        )

        self.assertEqual(result.task_type, "erp_lookup")
        self.assertEqual(result.lookup_operation, "inventory_lookup")
        self.assertEqual(result.lookup_query, "bombada")

    async def test_brand_catalog_is_llm_classified_and_keeps_traceable_query(self):
        service = StubIntentService(
            {
                "task_type": "erp_lookup",
                "decision": "erp_immediate",
                "confidence": 0.97,
                "need_profile_patch": {},
                "lookup_operation": "brand_catalog",
                "lookup_query": "釣竿",
            }
        )

        result = await service.analyze("目前釣竿品牌有哪些？")

        self.assertEqual(result.task_type, "erp_lookup")
        self.assertTrue(result.immediate)
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.lookup_operation, "brand_catalog")
        self.assertEqual(result.lookup_query, "釣竿")

    async def test_llm_catalog_query_cannot_invent_erp_lookup_subject(self):
        service = StubIntentService(
            {
                "task_type": "erp_lookup",
                "decision": "erp_immediate",
                "confidence": 0.97,
                "need_profile_patch": {},
                "lookup_operation": "brand_catalog",
                "lookup_query": "露營用品",
            }
        )

        result = await service.analyze("目前釣竿品牌有哪些？")

        self.assertEqual(result.task_type, "knowledge")
        self.assertFalse(result.immediate)
        self.assertIsNone(result.lookup_operation)
        self.assertIsNone(result.lookup_query)

    async def test_generic_inventory_management_question_does_not_use_erp(self):
        result = await ProductIntentAnalysisService().analyze("庫存管理方法有哪些？")
        self.assertEqual(result.decision, "knowledge_only")
        self.assertFalse(result.immediate)

    async def test_product_pricing_strategy_question_does_not_use_erp(self):
        result = await ProductIntentAnalysisService().analyze("產品價格策略應該怎麼制定？")
        self.assertEqual(result.decision, "knowledge_only")

    async def test_learning_recommendation_stays_in_knowledge_flow(self):
        service = StubIntentService(
            {"task_type": "knowledge", "decision": "knowledge_only", "confidence": 0.99, "need_profile_patch": {}}
        )
        result = await service.analyze("推薦一種學習方法")
        self.assertEqual(result.decision, "knowledge_only")
        self.assertFalse(result.bridge_eligible)

    async def test_llm_cannot_force_non_product_recommendation_into_erp(self):
        service = StubIntentService(
            {"task_type": "knowledge", "decision": "erp_immediate", "confidence": 0.8, "need_profile_patch": {}}
        )
        result = await service.analyze("推薦一個適合初學者的讀書方法")
        self.assertEqual(result.decision, "knowledge_only")
        self.assertFalse(result.immediate)

    async def test_equipment_recommendation_can_trigger_erp_and_patch_needs(self):
        service = StubIntentService(
            {
                "decision": "erp_immediate",
                "task_type": "product_recommendation",
                "confidence": 0.95,
                "need_profile_patch": {
                    "activity": "hiking",
                    "weather": ["rain"],
                    "categories": ["rain_protection", "lighting"],
                },
            }
        )
        result = await service.analyze("推薦玉山雨季裝備", bridge_eligible=True)
        self.assertTrue(result.immediate)
        self.assertEqual(result.need_profile_patch["activity"], "hiking")

    async def test_campsite_recommendation_is_a_destination_task_and_never_erp(self):
        service = StubIntentService(
            {
                "task_type": "destination_recommendation",
                "decision": "erp_immediate",
                "confidence": 0.98,
                "need_profile_patch": {},
            }
        )
        result = await service.analyze("南部中海拔營區推薦")
        self.assertEqual(result.task_type, "destination_recommendation")
        self.assertEqual(result.decision, "knowledge_only")
        self.assertFalse(result.immediate)

    async def test_campsite_filter_is_a_destination_task_and_never_erp(self):
        service = StubIntentService(
            {
                "task_type": "destination_filter",
                "decision": "knowledge_only",
                "confidence": 0.98,
                "need_profile_patch": {},
            }
        )
        result = await service.analyze(
            "依高雄出發地幫我篩選，三天的營地",
            context_state={"trip_plan": {"activity": "camping", "destination_region": "southern_taiwan"}},
        )
        self.assertEqual(result.task_type, "destination_filter")
        self.assertFalse(result.bridge_eligible)

    async def test_trip_followup_equipment_recommendation_can_enter_erp(self):
        service = StubIntentService(
            {
                "task_type": "product_recommendation",
                "decision": "erp_immediate",
                "confidence": 0.96,
                "need_profile_patch": {},
            }
        )
        result = await service.analyze(
            "合適的用品推薦",
            context_state={
                "trip_plan": {
                    "activity": "camping",
                    "destination_region": "southern_taiwan",
                    "elevation_band": "mid_altitude",
                    "departure_location": "高雄",
                    "duration_days": 3,
                }
            },
        )
        self.assertEqual(result.task_type, "product_recommendation")
        self.assertTrue(result.immediate)

    async def test_llm_failure_never_immediately_queries_erp_for_ambiguous_text(self):
        service = StubIntentService(error=RuntimeError("provider unavailable"))
        result = await service.analyze("你推薦怎麼準備玉山雨季？", bridge_eligible=True)
        self.assertEqual(result.decision, "knowledge_with_product_bridge")
        self.assertFalse(result.immediate)
        self.assertEqual(result.source, "fallback")

    async def test_llm_failure_keeps_campsite_query_out_of_erp(self):
        service = StubIntentService(error=RuntimeError("provider unavailable"))
        result = await service.analyze("南部中海拔營區推薦")
        self.assertEqual(result.task_type, "destination_recommendation")
        self.assertEqual(result.decision, "knowledge_only")


if __name__ == "__main__":
    unittest.main()
