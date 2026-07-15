import uuid
import unittest
from unittest.mock import AsyncMock, Mock, patch

from starlette.requests import Request

from src.api import routes_chat


class ChatProductFactIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_brand_inventory_query_persists_erp_fact_contract(self):
        conversation_id = uuid.uuid4()
        assistant_id = uuid.uuid4()
        lookup_payload = {
            "text": "ERP 找到 1 筆符合「bombada」的商品，目前總庫存為 20 件。",
            "product_results": [
                {
                    "sku": "P355302935",
                    "name": "Bombada Amazon Boonie - L Beige",
                    "brand": "",
                    "category": "綜合釣具",
                    "specification": "L Beige",
                    "price": 1200,
                    "stock": 20,
                    "recommendation_reason": "符合 Bombada 查詢，目前庫存為 20 件。",
                    "matched_requirements": ["erp_operation:inventory_lookup"],
                    "source_timestamp": "2026-07-15T00:00:00Z",
                }
            ],
            "erp_lookup": {
                "operation": "inventory_lookup",
                "query": "bombada",
                "status": "used",
                "matched_product_count": 1,
                "total_stock": 20,
                "timestamp": "2026-07-15T00:00:00Z",
                "data_quality_status": "complete",
                "truncated": False,
            },
        }

        async def save_message(_conversation_id, role, _content, **kwargs):
            if role == "assistant" and kwargs.get("return_message_id"):
                return conversation_id, assistant_id
            return conversation_id

        request = Request({"type": "http", "method": "POST", "path": "/chat", "query_string": b"", "headers": []})
        payload = {"message": "bombada還有多少庫存", "create_new_conversation": True, "lang": "zh-TW"}
        hooks = Mock()
        hooks.should_handle_business_fields.return_value = False

        with patch.object(routes_chat, "_get_payload", new=AsyncMock(return_value=payload)), \
             patch.object(routes_chat, "_ensure_conversation_write_access", new=AsyncMock()), \
             patch.object(routes_chat, "is_module_enabled", return_value=True), \
             patch.object(routes_chat, "chat_domain_hooks", hooks), \
             patch.object(routes_chat.product_fact_lookup_service, "lookup", new=AsyncMock(return_value=lookup_payload)) as lookup, \
             patch.object(routes_chat, "add_message_to_conversation", new=AsyncMock(side_effect=save_message)), \
             patch.object(routes_chat, "update_message_enrichment", new=AsyncMock()) as enrich, \
             patch.object(routes_chat, "merge_conversation_context_state", new=AsyncMock()) as save_context:
            response = await routes_chat.chat(
                request,
                user={"id": str(uuid.uuid4()), "username": "tester", "role": "admin"},
            )

        self.assertTrue(response["ok"])
        self.assertEqual(response["intent"]["name"], "ERP_PRODUCT_FACT_LOOKUP")
        self.assertEqual(response["product_results"][0]["sku"], "P355302935")
        metadata = response["answer"]["metadata"]
        self.assertEqual(metadata["intent_task_type"], "erp_lookup")
        self.assertEqual(metadata["intent_lookup_operation"], "inventory_lookup")
        self.assertEqual(metadata["erp_lookup"]["query"], "bombada")
        self.assertEqual(metadata["erp_lookup"]["total_stock"], 20)
        self.assertFalse(metadata["knowledge"]["external_attempted"])
        lookup.assert_awaited_once_with("inventory_lookup", "bombada", "zh-Hant")
        enrich.assert_awaited_once()
        save_context.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
