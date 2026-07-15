import unittest

from src.services.ai.product_bridge import ProductBridgeService


class FakeCerpService:
    def __init__(self, products):
        self.products = products
        self.calls = 0

    async def fetch_top_stock_products(self, **_kwargs):
        self.calls += 1
        return list(self.products)


class ProductBridgeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_only_real_erp_products_in_public_contract(self):
        cerp = FakeCerpService(
            [
                {
                    "no": "CAMP0002",
                    "name": "Rain Tarp",
                    "brand": "PinePeak",
                    "category": "Tarp & Canopy",
                    "spec": "4x4m waterproof",
                    "price": 1800,
                    "stock": 12,
                },
                {
                    "no": "CAMP0005",
                    "name": "LED Lantern",
                    "brand": "NorthTrek",
                    "category": "Lighting",
                    "spec": "1000lm",
                    "price": 900,
                    "stock": 4,
                },
            ]
        )
        service = ProductBridgeService(cerp)

        result = await service.recommend(
            {
                "categories": ["rain_protection", "lighting"],
                "required_features": [],
                "excluded_features": [],
                "preferred_brands": [],
                "budget": {"max": 2000, "currency": "TWD"},
                "weather": ["rain"],
            }
        )

        self.assertEqual(cerp.calls, 1)
        self.assertEqual({item["sku"] for item in result["product_results"]}, {"CAMP0002", "CAMP0005"})
        for item in result["product_results"]:
            self.assertEqual(
                set(item),
                {
                    "sku",
                    "name",
                    "brand",
                    "category",
                    "specification",
                    "price",
                    "stock",
                    "recommendation_reason",
                    "matched_requirements",
                    "source_timestamp",
                },
            )
            self.assertNotIn("category:", item["recommendation_reason"])
            self.assertNotIn("rain_protection", item["recommendation_reason"])

    async def test_query_plan_uses_need_features_and_searches_erp(self):
        class SearchableCerp(FakeCerpService):
            def __init__(self):
                super().__init__([])
                self.terms = []

            async def search_products(self, term, **_kwargs):
                self.terms.append(term)
                return []

        cerp = SearchableCerp()
        service = ProductBridgeService(cerp)
        result = await service.recommend(
            {
                "activity": "hiking",
                "location": "玉山",
                "duration": "2天",
                "party_size": 3,
                "quantity": 2,
                "weather": ["rain"],
                "categories": ["rain_protection", "storage_packs"],
                "required_features": ["lightweight"],
            }
        )
        self.assertIn("rain jacket", cerp.terms)
        self.assertIn("backpack", cerp.terms)
        self.assertIn("lightweight", cerp.terms)
        self.assertEqual(result["query_plan"]["location"], "玉山")
        self.assertEqual(result["query_plan"]["duration"], "2天")
        self.assertEqual(result["query_plan"]["party_size"], 3)
        self.assertEqual(result["query_plan"]["stock_min"], 2)

    async def test_hiking_request_rejects_camping_tarp(self):
        service = ProductBridgeService(
            FakeCerpService(
                [{
                    "no": "CAMP-TARP-1",
                    "name": "Rain Tarp",
                    "category": "Tarp & Canopy",
                    "specification": "4x4m waterproof",
                    "stock": 5,
                    "price": 2000,
                }]
            )
        )
        result = await service.recommend(
            {"activity": "hiking", "weather": ["rain"], "categories": ["rain_protection"]}
        )
        self.assertEqual(result["product_results"], [])

    async def test_specification_uses_canonical_alias_order(self):
        service = ProductBridgeService(
            FakeCerpService(
                [{
                    "no": "ERP-SPEC-1",
                    "name": "Waterproof Dry Bag",
                    "category": "Storage & Packs",
                    "invn807": "40L / reinforced",
                    "stock": 5,
                    "price": 1500,
                }]
            )
        )
        result = await service.recommend({"categories": ["storage_packs"]})
        self.assertEqual(result["product_results"][0]["specification"], "40L / reinforced")

    async def test_no_match_never_invents_product_facts(self):
        service = ProductBridgeService(FakeCerpService([]))

        result = await service.recommend({"categories": ["safety_repair"], "weather": []})

        self.assertEqual(result["product_results"], [])
        self.assertEqual(result["erp_status"], "no_matches")
        self.assertIn("ERP", result["text"])

    async def test_excluded_brand_is_not_returned(self):
        service = ProductBridgeService(
            FakeCerpService(
                [
                    {
                        "no": "CAMP0002",
                        "name": "Rain Tarp",
                        "brand": "PinePeak",
                        "category": "Tarp & Canopy",
                        "price": 1800,
                        "stock": 12,
                    }
                ]
            )
        )

        result = await service.recommend(
            {
                "categories": ["rain_protection"],
                "excluded_features": ["brand:PinePeak"],
                "weather": ["rain"],
            }
        )

        self.assertEqual(result["product_results"], [])

    async def test_reason_uses_trip_context_and_only_actual_erp_facts(self):
        service = ProductBridgeService(
            FakeCerpService(
                [{
                    "no": "CAMP-SLEEP-1",
                    "name": "Alpine Sleeping Bag",
                    "category": "Sleeping Bag",
                    "specification": "Comfort 5°C",
                    "stock": 7,
                    "price": 3200,
                }]
            )
        )
        result = await service.recommend(
            {
                "activity": "camping",
                "location": "南部中海拔",
                "duration": "3天",
                "categories": ["sleeping_gear"],
            },
            language="zh-TW",
        )
        reason = result["product_results"][0]["recommendation_reason"]
        self.assertIn("3天", reason)
        self.assertIn("中海拔", reason)
        self.assertIn("Comfort 5°C", reason)
        self.assertIn("目前有庫存", reason)
        self.assertNotIn("高雄", reason)
        self.assertNotRegex(reason, r"category:|[a-z]+_[a-z_]+")


if __name__ == "__main__":
    unittest.main()
