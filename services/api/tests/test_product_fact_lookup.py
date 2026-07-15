import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cerpModule import CERPClientError
from src.services.ai.product_fact_lookup import ProductFactLookupService


def _product(**overrides):
    row = {
        "no": "P355302935",
        "name": "Bombada Fishing Rod",
        "brand": "Bombada",
        "supplier": "Fishing Importer",
        "category": "釣竿",
        "specification": "7 ft",
        "price": 3200,
        "stock": 20,
    }
    row.update(overrides)
    return row


class ProductFactLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_inventory_lookup_uses_traceable_query_and_live_stock_total(self):
        cerp = Mock()
        cerp.search_products = AsyncMock(return_value=[_product()])
        service = ProductFactLookupService(cerp)

        result = await service.lookup("inventory_lookup", "bombada", "zh-TW")

        cerp.search_products.assert_awaited_once_with(
            "bombada", limit=200, page_size=100, raise_on_error=True
        )
        self.assertEqual(result["erp_lookup"]["status"], "used")
        self.assertEqual(result["erp_lookup"]["total_stock"], 20)
        self.assertEqual(result["product_results"][0]["sku"], "P355302935")
        self.assertIn("目前庫存為 20 件", result["product_results"][0]["recommendation_reason"])

    async def test_brand_catalog_never_promotes_supplier_to_brand(self):
        cerp = Mock()
        cerp.search_products = AsyncMock(
            return_value=[
                _product(brand="", supplier="YS 釣竿供應"),
                _product(no="P2", name="Second 釣竿", brand="", supplier="Other Supplier", stock=4),
            ]
        )
        result = await ProductFactLookupService(cerp).lookup("brand_catalog", "釣竿", "zh-TW")

        self.assertEqual(result["erp_lookup"]["status"], "brand_missing")
        self.assertEqual(result["erp_lookup"]["brands"], [])
        self.assertEqual(result["erp_lookup"]["brand_missing_count"], 2)
        self.assertNotIn("YS 釣竿供應", result["text"])
        self.assertIn("未提供品牌資料", result["text"])
        self.assertTrue(all(item["brand"] == "" for item in result["product_results"]))

    async def test_brand_catalog_aggregates_only_explicit_brands(self):
        cerp = Mock()
        cerp.search_products = AsyncMock(
            return_value=[
                _product(),
                _product(no="P2", name="Bombada Travel 釣竿", stock=0),
                _product(no="P3", name="Unbranded 釣竿", brand="", supplier="YS 釣竿供應", stock=3),
            ]
        )
        result = await ProductFactLookupService(cerp).lookup("brand_catalog", "釣竿", "en")

        self.assertEqual(result["erp_lookup"]["status"], "used")
        self.assertEqual(result["erp_lookup"]["data_quality_status"], "partial_brand_missing")
        self.assertEqual(
            result["erp_lookup"]["brands"],
            [{"brand": "Bombada", "product_count": 2, "in_stock_product_count": 1, "total_stock": 20}],
        )

    async def test_postfilter_rejects_unrelated_cerp_candidate(self):
        cerp = Mock()
        cerp.search_products = AsyncMock(return_value=[_product(name="Unrelated tent", brand="Other", category="帳篷")])
        result = await ProductFactLookupService(cerp).lookup("product_lookup", "釣竿", "zh-TW")
        self.assertEqual(result["erp_lookup"]["status"], "no_matches")
        self.assertEqual(result["product_results"], [])

    async def test_compound_brand_and_category_subject_matches_across_erp_fields(self):
        product = _product(name="Bombada Travel Rod", brand="Bombada", category="釣竿")
        cerp = Mock()
        cerp.search_products = AsyncMock(side_effect=[[], [product], [product]])

        result = await ProductFactLookupService(cerp).lookup(
            "inventory_lookup", "bombada釣竿", "zh-TW"
        )

        self.assertEqual(result["erp_lookup"]["status"], "used")
        self.assertEqual(result["erp_lookup"]["total_stock"], 20)
        self.assertEqual(result["product_results"][0]["sku"], "P355302935")

    async def test_cerp_failure_is_distinct_from_no_matches(self):
        cerp = Mock()
        cerp.search_products = AsyncMock(side_effect=CERPClientError("offline"))
        result = await ProductFactLookupService(cerp).lookup("inventory_lookup", "bombada", "zh-TW")
        self.assertEqual(result["erp_lookup"]["status"], "error")
        self.assertNotIn("找不到", result["text"])


if __name__ == "__main__":
    unittest.main()
