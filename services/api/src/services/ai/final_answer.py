from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from ...pipelines.llm.openai_client import LLMRequestBudget, chat_complete_result
from ...schemas.ai import Hit
from .chat_planner import ChatExecutionPlan


class ERPClaim(BaseModel):
    text: str = Field(min_length=1, max_length=800)
    proof_ids: List[str] = Field(default_factory=list, max_length=12)


class FinalAnswerPayload(BaseModel):
    knowledge_text: str = ""
    citation_ids: List[str] = Field(default_factory=list, max_length=6)
    erp_claims: List[ERPClaim] = Field(default_factory=list, max_length=12)


class FinalAnswerService:
    async def generate(
        self,
        query: str,
        *,
        plan: ChatExecutionPlan,
        hits: Sequence[Hit],
        external_status: Dict[str, Any],
        erp_result: Optional[Dict[str, Any]],
        history: Optional[Sequence[Dict[str, Any]]],
        language: Optional[str],
        budget: LLMRequestBudget,
    ) -> Dict[str, Any]:
        evidence = [
            {
                "id": str(hit.id or index),
                "text": str(hit.summary or hit.text or "")[:700],
                "source_type": hit.source_type,
                "source_tier": hit.source_tier,
                "url": (hit.meta or {}).get("url"),
            }
            for index, hit in enumerate(hits[:6])
        ]
        result_payload = erp_result if isinstance(erp_result, dict) else {}
        proofs = [item for item in result_payload.get("row_proofs") or [] if isinstance(item, dict)]
        products = [item for item in result_payload.get("product_results") or [] if isinstance(item, dict)][:6]
        recent = [
            {
                "role": str(item.get("role") or "user"),
                "content": str(item.get("content") or "")[:400],
            }
            for item in list(history or [])[-12:]
            if isinstance(item, dict) and str(item.get("content") or "").strip()
        ]
        user_payload = {
            "query": query,
            "plan": plan.model_dump(mode="json"),
            "retrieved_evidence": evidence,
            "external_status": external_status,
            "erp_products": products,
            "erp_row_proofs": proofs,
            "recent_history": recent,
        }
        system = (
            "You are the final answer model for YS-AI. Return only the requested JSON schema. "
            "Always provide a useful knowledge_text for knowledge or mixed requests, even when RAG has no hits, "
            "external search is unavailable, or ERP has no results. Use general model knowledge when evidence is absent. "
            "When the requested fact is genuinely live and external evidence is unavailable, clearly separate general "
            "guidance from the current fact that could not be confirmed; never claim verification. Do not mention provider "
            "configuration for stable knowledge questions. Use only retrieved evidence IDs that materially support the answer. "
            "All actual YS product, SKU, brand, price, stock, quote, and availability facts must be emitted as erp_claims, "
            "and every ERP claim must cite the exact ERP proof IDs supplied. Never create a product fact or proof ID. "
            "For mixed questions, put professional guidance in knowledge_text and ERP facts in erp_claims. "
            "Answer in the same language as the user's latest message."
        )
        result = await chat_complete_result(
            system=system,
            user=json.dumps(user_payload, ensure_ascii=False),
            history=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
            temperature=0.3,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ys_final_answer",
                    "strict": False,
                    "schema": FinalAnswerPayload.model_json_schema(),
                },
            },
            max_completion_tokens=1800,
            budget=budget,
            role="final",
            allow_model_fallback=False,
        )
        parsed = FinalAnswerPayload.model_validate(self._parse_json(result.content))
        return self._validate_and_assemble(
            parsed,
            plan=plan,
            hits=hits,
            proofs=proofs,
            erp_result=result_payload,
            language=language,
        )

    @staticmethod
    def _parse_json(value: str) -> Dict[str, Any]:
        text = str(value or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Final answer response must be an object")
        return parsed

    @classmethod
    def _validate_and_assemble(
        cls,
        payload: FinalAnswerPayload,
        *,
        plan: ChatExecutionPlan,
        hits: Sequence[Hit],
        proofs: Sequence[Dict[str, Any]],
        erp_result: Dict[str, Any],
        language: Optional[str],
    ) -> Dict[str, Any]:
        hit_map = {str(hit.id): hit for hit in hits if hit.id is not None}
        citation_ids = [item for item in payload.citation_ids if item in hit_map]
        proof_ids = {str(item.get("id")) for item in proofs if item.get("id")}
        valid_claims: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for claim in payload.erp_claims:
            supplied = list(dict.fromkeys(str(item) for item in claim.proof_ids if str(item)))
            if supplied and all(item in proof_ids for item in supplied):
                valid_claims.append({"text": claim.text.strip(), "proof_ids": supplied})
            else:
                rejected.append({"text": claim.text.strip(), "proof_ids": supplied})

        sections: List[Dict[str, Any]] = []
        knowledge_text = payload.knowledge_text.strip()
        if knowledge_text:
            sections.append({"type": "knowledge", "label": cls._section_label("knowledge", language), "text": knowledge_text})
        erp_text = "\n".join(item["text"] for item in valid_claims if item["text"]).strip()
        if plan.erp_ast is not None and not erp_text:
            erp_text = str(erp_result.get("text") or cls._erp_fallback(erp_result, language)).strip()
        if erp_text:
            sections.append({"type": "erp", "label": cls._section_label("erp", language), "text": erp_text})
        show_labels = plan.answer_mode == "mixed" and len(sections) > 1
        text = "\n\n".join(
            f"### {item['label']}\n\n{item['text']}" if show_labels else item["text"]
            for item in sections
            if item["text"]
        ).strip()
        if not text:
            text = cls._general_fallback(language)
            sections = [{"type": "knowledge", "text": text}]
        return {
            "text": text,
            "citations": [hit_map[item].model_dump() for item in citation_ids],
            "answer_sections": sections,
            "claim_validation": {
                "status": "passed" if not rejected else "partial",
                "supported_claim_count": len(valid_claims),
                "unsupported_claim_count": len(rejected),
                "unsupported_claims": rejected,
                "row_proof_count": len(proof_ids),
            },
        }

    @staticmethod
    def _section_label(kind: str, language: Optional[str]) -> str:
        locale = str(language or "").lower()
        if locale.startswith("en"):
            return "Professional guidance" if kind == "knowledge" else "YS ERP products"
        if locale.startswith("ja"):
            return "専門的な提案" if kind == "knowledge" else "YS ERP 商品"
        return "專業建議" if kind == "knowledge" else "YS ERP 商品"

    @staticmethod
    def _erp_fallback(result: Dict[str, Any], language: Optional[str]) -> str:
        lookup = result.get("erp_lookup") if isinstance(result.get("erp_lookup"), dict) else {}
        status = str(lookup.get("status") or "")
        locale = str(language or "").lower()
        if locale.startswith("en"):
            return "YS ERP has no matching product data." if status == "no_matches" else "The YS ERP result is shown in the product cards below."
        if locale.startswith("ja"):
            return "YS ERP に一致する商品データはありません。" if status == "no_matches" else "YS ERP の結果は下の商品カードに表示されています。"
        return "YS ERP 目前沒有符合條件的商品資料。" if status == "no_matches" else "YS ERP 查詢結果已列於下方商品卡。"

    @staticmethod
    def _general_fallback(language: Optional[str]) -> str:
        locale = str(language or "").lower()
        if locale.startswith("en"):
            return "I can still provide general guidance, but the answer could not be fully assembled."
        if locale.startswith("ja"):
            return "一般的な案内は可能ですが、回答を完全には構成できませんでした。"
        return "我仍可提供一般建議，但這次未能完整組合回答。"
