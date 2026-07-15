import unittest

from src.services.ai.chat_planner import ChatExecutionPlan
from src.services.ai.final_answer import ERPClaim, FinalAnswerPayload, FinalAnswerService


class FinalAnswerValidationTests(unittest.TestCase):
    def test_mixed_answer_keeps_knowledge_and_only_proven_erp_claims(self):
        plan = ChatExecutionPlan.model_validate(
            {
                "task_type": "mixed",
                "answer_mode": "mixed",
                "rag_queries": ["雨季登山準備"],
                "erp_ast": {
                    "operation": "inventory",
                    "search_terms": [
                        {
                            "value": "Bombada",
                            "source_trace": {"source": "current_message", "reference": "Bombada"},
                        }
                    ],
                },
            }
        )
        payload = FinalAnswerPayload(
            knowledge_text="雨季登山應優先管理失溫與裝備乾燥。",
            erp_claims=[
                ERPClaim(text="Bombada 目前庫存為 20 件。", proof_ids=["ERP:P1#stock"]),
                ERPClaim(text="另一商品庫存為 99 件。", proof_ids=["ERP:FAKE#stock"]),
            ],
        )
        result = FinalAnswerService._validate_and_assemble(
            payload,
            plan=plan,
            hits=[],
            proofs=[{"id": "ERP:P1#stock", "value": 20}],
            erp_result={"text": "ERP fallback"},
            language="zh-TW",
        )
        self.assertIn("雨季登山", result["text"])
        self.assertIn("20 件", result["text"])
        self.assertNotIn("99 件", result["text"])
        self.assertEqual(result["claim_validation"]["unsupported_claim_count"], 1)

    def test_external_failure_does_not_replace_knowledge_text(self):
        plan = ChatExecutionPlan(
            task_type="destination",
            answer_mode="knowledge_only",
            rag_queries=["中海拔營地"],
            external={"required": True, "query": "中海拔營地營運", "reason": "current_operation"},
        )
        result = FinalAnswerService._validate_and_assemble(
            FinalAnswerPayload(
                knowledge_text="可先依車程、海拔、道路與設施篩選；目前營運與空位仍須向營地確認。"
            ),
            plan=plan,
            hits=[],
            proofs=[],
            erp_result={},
            language="zh-TW",
        )
        self.assertIn("依車程", result["text"])
        self.assertNotIn("provider", result["text"].lower())


if __name__ == "__main__":
    unittest.main()

