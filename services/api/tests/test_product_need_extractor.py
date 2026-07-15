import unittest

from src.services.ai.product_need_extractor import ProductNeedExtractor


class ProductNeedExtractorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.extractor = ProductNeedExtractor()

    def test_knowledge_question_creates_button_profile_without_immediate_intent(self):
        result = self.extractor.extract("玉山雨季如何準備？")

        self.assertTrue(result.eligible)
        self.assertFalse(result.explicit_product_intent)
        self.assertEqual(result.profile["activity"], "hiking")
        self.assertEqual(result.profile["location"], "玉山")
        self.assertIn("rain", result.profile["weather"])
        self.assertIn("rain_protection", result.profile["categories"])

    def test_recommendation_waits_for_semantic_intent_analysis(self):
        result = self.extractor.extract("直接推薦玉山雨季裝備")

        self.assertTrue(result.eligible)
        self.assertFalse(result.explicit_product_intent)

    def test_pure_knowledge_without_product_context_has_no_bridge(self):
        result = self.extractor.extract("請解釋牛頓第二運動定律")

        self.assertFalse(result.eligible)
        self.assertFalse(result.explicit_product_intent)

    def test_followup_inherits_profile_and_lowers_budget(self):
        first = self.extractor.extract("推薦預算 5000 的露營帳篷")
        history = [
            {
                "role": "assistant",
                "metadata": {"product_bridge": {"eligible": True, "need_profile": first.profile}},
            }
        ]

        result = self.extractor.extract("更便宜一點", history=history)

        self.assertFalse(result.explicit_product_intent)
        self.assertEqual(result.profile["activity"], "camping")
        self.assertEqual(result.profile["budget"]["max"], 4000.0)

    def test_brand_exclusion_uses_only_saved_erp_result(self):
        first = self.extractor.extract("推薦露營裝備")
        history = [
            {
                "role": "assistant",
                "metadata": {
                    "product_bridge": {"eligible": True, "need_profile": first.profile},
                    "product_results": [{"sku": "ERP-1", "brand": "TrailForge"}],
                },
            }
        ]

        result = self.extractor.extract("不要這個品牌", history=history)

        self.assertIn("brand:TrailForge", result.profile["excluded_features"])

    def test_cheaper_followup_uses_saved_erp_price_when_budget_was_not_set(self):
        first = self.extractor.extract("Recommend camping gear")
        history = [
            {
                "role": "assistant",
                "metadata": {
                    "product_bridge": {"eligible": True, "need_profile": first.profile},
                    "product_results": [{"sku": "ERP-1", "price": 2500}],
                },
            }
        ]

        result = self.extractor.extract("cheaper", history=history)

        self.assertFalse(result.explicit_product_intent)
        self.assertEqual(result.profile["budget"]["max"], 2000.0)


if __name__ == "__main__":
    unittest.main()
