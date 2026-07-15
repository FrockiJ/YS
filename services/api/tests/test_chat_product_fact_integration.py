import uuid
import unittest
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from src.api import routes_chat
from src.schemas.ai import ChatResponse, Intent
from src.services.ai.chat_planner import ChatExecutionPlan


class ChatProductFactIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_brand_inventory_uses_planner_ast_and_preserves_contract(self):
        assistant_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        plan = ChatExecutionPlan.model_validate(
            {
                "task_type": "erp_lookup",
                "answer_mode": "erp_only",
                "rag_queries": [],
                "external": {"required": False},
                "erp_ast": {
                    "operation": "inventory",
                    "projections": ["sku", "name", "stock"],
                    "search_terms": [
                        {
                            "value": "bombada",
                            "match": "fuzzy",
                            "fields": ["name", "brand"],
                            "source_trace": {"source": "current_message", "reference": "bombada"},
                        }
                    ],
                },
                "confidence": 0.99,
            }
        )
        product = {
            "sku": "P355302935",
            "name": "Bombada Amazon Boonie",
            "brand": "",
            "category": "綜合釣具",
            "specification": "L Beige",
            "price": 1200,
            "stock": 20,
            "recommendation_reason": "此 ERP 商品符合模糊查詢。",
            "matched_requirements": ["term:0"],
            "source_timestamp": "2026-07-15T00:00:00Z",
        }
        erp_result = {
            "text": "YS ERP 找到 1 筆商品，目前總庫存為 20 件。",
            "product_results": [product],
            "row_proofs": [{"id": "ERP:P355302935#stock", "value": 20}],
            "erp_lookup": {
                "operation": "inventory_lookup",
                "query": "bombada",
                "status": "used",
                "matched_product_count": 1,
                "total_stock": 20,
                "timestamp": "2026-07-15T00:00:00Z",
            },
            "erp_query": {
                "ast_version": "2",
                "operation": "inventory",
                "row_proof_count": 1,
                "status": "used",
                "timestamp": "2026-07-15T00:00:00Z",
            },
        }
        metadata = {
            "response_mode": "generated",
            "prompt_category": "general_chat",
            "retrieval_snapshot": {"rag_status": "empty_corpus", "rag_hit_count": 0, "selected_hit_count": 0},
            "external_search": {"attempted": False},
            "execution_plan": plan.audit_metadata(),
            "erp_lookup": erp_result["erp_lookup"],
            "erp_query": erp_result["erp_query"],
            "product_results": [product],
            "llm_budget": {"limit": 2, "used": 2, "planner_calls": 1, "final_calls": 1},
        }
        orchestrated = ChatResponse(
            intent=Intent(name="FREE_CHAT"),
            answer={
                "text": "YS ERP 顯示 Bombada 目前庫存為 20 件。",
                "citations": [],
                "conversation_id": str(conversation_id),
                "message_id": str(assistant_id),
                "metadata": metadata,
            },
            content="YS ERP 顯示 Bombada 目前庫存為 20 件。",
        )
        request = Request({"type": "http", "method": "POST", "path": "/chat", "query_string": b"", "headers": []})
        payload = {"message": "bombada還有多少庫存", "create_new_conversation": True, "lang": "zh-TW"}

        with patch.object(routes_chat, "_get_payload", new=AsyncMock(return_value=payload)), \
             patch.object(routes_chat, "_ensure_conversation_write_access", new=AsyncMock()), \
             patch.object(routes_chat, "is_module_enabled", return_value=True), \
             patch.object(routes_chat.chat_planning_service, "plan", new=AsyncMock(return_value=plan)), \
             patch.object(routes_chat.erp_query_executor, "execute", new=AsyncMock(return_value=erp_result)) as execute, \
             patch.object(routes_chat.chat_orchestrator, "chat", new=AsyncMock(return_value=orchestrated)) as orchestrate, \
             patch.object(routes_chat, "update_message_enrichment", new=AsyncMock()), \
             patch.object(routes_chat, "merge_conversation_context_state", new=AsyncMock()):
            response = await routes_chat.chat(
                request,
                user={"id": 1, "username": "tester", "role": "admin"},
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["product_results"][0]["sku"], "P355302935")
        answer_metadata = response["answer"]["metadata"]
        self.assertEqual(answer_metadata["intent_task_type"], "erp_lookup")
        self.assertEqual(answer_metadata["intent_lookup_operation"], "inventory_lookup")
        self.assertEqual(answer_metadata["erp_query"]["ast_version"], "2")
        self.assertFalse(answer_metadata["knowledge"]["external_attempted"])
        execute.assert_awaited_once()
        self.assertFalse(orchestrate.await_args.kwargs["needs_authoritative_sources"])


if __name__ == "__main__":
    unittest.main()
