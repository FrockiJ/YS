import unittest
from unittest.mock import AsyncMock

from src.services.ai.chat_planner import ERPQueryAST
from src.services.ai.erp_ast import ERPQueryExecutor


def _ast(operation="recommendation"):
    return ERPQueryAST.model_validate(
        {
            "version": "2",
            "operation": operation,
            "projections": ["sku", "name", "brand", "category", "specification", "price", "stock"],
            "search_terms": [
                {
                    "value": "Bombada 釣具",
                    "match": "fuzzy",
                    "fields": ["name", "brand", "category"],
                    "source_trace": {
                        "source": "current_message",
                        "reference": "Bombada 釣具",
                    },
                }
            ],
            "predicates": [
                {
                    "field": "stock",
                    "operator": "gte",
                    "value": 1,
                    "source_trace": {"source": "current_message", "reference": "有庫存"},
                }
            ],
            "ranking": [{"criterion": "stock", "weight": 1}],
            "limit": 6,
        }
    )


class ERPQueryExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_ast_terms_and_emits_field_level_row_proofs(self):
        cerp = AsyncMock()
        cerp.search_products.return_value = [
            {
                "no": "P355302935",
                "name": "Bombada fishing rod",
                "brand": "Bombada",
                "category": "釣具",
                "specification": "7 ft",
                "price": 2800,
                "stock": 20,
            }
        ]
        result = await ERPQueryExecutor(cerp).execute(_ast(), language="zh-TW")
        self.assertEqual(result["erp_query"]["ast_version"], "2")
        self.assertEqual(result["erp_query"]["row_proof_count"], 7)
        self.assertEqual(result["product_results"][0]["sku"], "P355302935")
        reason = result["product_results"][0]["recommendation_reason"]
        self.assertNotIn("fuzzy", reason.casefold())
        self.assertNotIn("term:", reason.casefold())
        self.assertIn("7 ft", reason)
        self.assertTrue(all(item["id"].startswith("ERP:P355302935#") for item in result["row_proofs"]))
        cerp.search_products.assert_awaited_once_with(
            "Bombada 釣具", limit=50, page_size=50, raise_on_error=True
        )

    async def test_predicates_filter_unproven_products_without_filling_results(self):
        cerp = AsyncMock()
        cerp.search_products.return_value = [
            {"no": "P1", "name": "Bombada fishing rod", "category": "釣具", "stock": 0}
        ]
        result = await ERPQueryExecutor(cerp).execute(_ast(), language="zh-TW")
        self.assertEqual(result["erp_lookup"]["status"], "no_matches")
        self.assertEqual(result["product_results"], [])


if __name__ == "__main__":
    unittest.main()
