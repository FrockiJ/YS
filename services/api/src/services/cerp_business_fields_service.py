from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .ai.answer_route_policy import build_answer_route_policy
from .ai.evidence_contracts import build_cerp_evidence_contract
from .cerp_service import CerpService
from ..core.i18n import t


FIELD_PATTERNS: Dict[str, re.Pattern[str]] = {
    "cost": re.compile(r"\b(?:cost|landed cost|wholesale)\b|成本", re.IGNORECASE),
    "margin": re.compile(r"\b(?:margin|gross margin|margin rate)\b|毛利", re.IGNORECASE),
    "supplier_terms": re.compile(r"\b(?:supplier terms?|supplier payment terms?|payment terms?)\b|供應商付款|付款條件", re.IGNORECASE),
    "sales_velocity": re.compile(r"\b(?:sales velocity|recent sales|sell[-\s]?through)\b|銷售速度", re.IGNORECASE),
    "depletion": re.compile(r"\bdepletion\b|去化", re.IGNORECASE),
    "allocation": re.compile(r"\ballocation\b|配額", re.IGNORECASE),
    "order_history": re.compile(r"\b(?:order history|purchase history|reorder|next order)\b|訂貨|補貨|下次訂貨", re.IGNORECASE),
    "review_score": re.compile(r"\b(?:review score|rating|score|points?)\b|評分|分數", re.IGNORECASE),
}

CERP_SIGNAL_RE = re.compile(
    r"\b(?:cerp|sku|inventory|stock|product code|item code)\b|[A-Z]{2,}[A-Z0-9]*-[A-Z0-9-]{4,}|庫存|品號|商品代號",
    re.IGNORECASE,
)

FIELD_LABELS = {
    "cost": "Cost",
    "margin": "Margin",
    "margin_rate": "Margin rate",
    "supplier_terms": "Supplier terms",
    "sales_velocity": "Sales velocity",
    "depletion": "Depletion",
    "allocation": "Allocation",
    "order_history": "Order history",
    "review_score": "Review score",
}

QUERY_STOP_RE = re.compile(
    r"\b(?:show|give|list|tell|me|all|for|from|of|the|and|with|cerp|data|field|fields|cost|margin|gross|landed|"
    r"supplier|payment|terms|sales|velocity|depletion|allocation|order|history|reorder|next|review|score|rating|points?)\b",
    re.IGNORECASE,
)


class CerpBusinessFieldsService:
    """CERP-only deterministic path for commercial fields available to logged-in users."""

    def __init__(self, cerp_service: Optional[CerpService] = None) -> None:
        self._cerp_service = cerp_service or CerpService()

    @classmethod
    def requested_fields(cls, query: str) -> List[str]:
        fields: List[str] = []
        for field, pattern in FIELD_PATTERNS.items():
            if pattern.search(query or ""):
                fields.append(field)
                if field == "margin" and "margin_rate" not in fields:
                    fields.append("margin_rate")
        return fields

    @classmethod
    def should_handle(cls, query: str) -> bool:
        fields = cls.requested_fields(query)
        if not fields:
            return False
        if set(fields).issubset({"review_score"}) and not CERP_SIGNAL_RE.search(query or ""):
            return False
        return True

    async def answer(self, query: str, *, language: str = "zh-Hant", limit: int = 10) -> Dict[str, Any]:
        requested = self.requested_fields(query)
        product_query = self._product_query(query)
        products = await self._cerp_service.search_products(
            product_query or query,
            limit=limit,
            raise_on_error=True,
        )
        generated_at = datetime.now(timezone.utc).isoformat()
        items, present_fields = self._build_items(products, requested, generated_at=generated_at)
        missing_fields = [field for field in requested if field not in present_fields]
        verified = bool(items) and bool(present_fields)
        partial_framework = (not verified) and self._should_return_decision_framework(query, requested)
        answer_text = self._build_answer_text(
            query=query,
            product_query=product_query,
            items=items,
            requested_fields=requested,
            missing_fields=missing_fields,
            verified=verified,
            partial_framework=partial_framework,
            language=language,
        )
        cerp_results = {
            "kind": "cerp_business_snapshot",
            "count": len(items),
            "proof_count": len(items) if verified else 0,
            "source": "CERP",
            "generated_at": generated_at,
            "requested_fields": requested,
            "field_names": sorted(present_fields),
            "missing_fields": missing_fields,
            "items": items,
        }
        route_policy = build_answer_route_policy(
            prompt_category="cerp_business_lookup",
            intent_name="CERP_BUSINESS_LOOKUP",
            entity_hints={},
            context_state={},
            source_policy="internal_only",
        )
        route_policy["evidence_type"] = "cerp_business_snapshot"
        evidence_contract = build_cerp_evidence_contract(
            cerp_products=products if verified else [],
            prompt_category="cerp_business_lookup",
            source_policy="internal_only",
            route_policy=route_policy,
        )
        evidence_contract["evidence_type"] = "cerp_business_snapshot"
        if not verified and not partial_framework:
            evidence_contract["status"] = "fail"
            evidence_contract["fail_closed_reason"] = "cerp_field_missing"
            evidence_contract["missing_contract_fields"] = missing_fields or requested
        elif not verified:
            evidence_contract["status"] = "partial_pass"
            evidence_contract["partial_pass_reason"] = "cerp_fields_unavailable_with_decision_framework"
            evidence_contract["missing_contract_fields"] = missing_fields or requested
        official_binding = {
            "required": True,
            "proof_count": cerp_results["proof_count"],
            "proofs": [item["proof"] for item in items] if verified else [],
            "source": "CERP",
            "timestamp": generated_at,
            "requested_fields": requested,
            "field_names": sorted(present_fields),
            "missing_fields": missing_fields,
        }
        unavailable_flag = "cerp_field_unavailable_verified" if partial_framework else "cerp_field_missing"
        metadata = {
            "intent": "CERP_BUSINESS_LOOKUP",
            "prompt_category": "cerp_business_lookup",
            "answer_mode": "cerp_business_snapshot" if verified else ("partial_answer_with_gaps" if partial_framework else "fail_closed"),
            "answer_verification_mode": "verified_answer" if verified else ("partial_answer_with_gaps" if partial_framework else "data_or_permission_needed"),
            "answer_verification": {
                "mode": "verified_answer" if verified else ("partial_answer_with_gaps" if partial_framework else "data_or_permission_needed"),
                "verified": verified,
                "requires_disclaimer": partial_framework,
                "reason": "cerp_business_snapshot_proof" if verified else unavailable_flag,
            },
            "response_mode": "cerp_business_snapshot" if verified else ("answerable_with_gaps" if partial_framework else "templated_fail_closed"),
            "substantive_answer": bool(verified or partial_framework),
            "gap_reason": "cerp_field_missing" if partial_framework else "",
            "source_policy": "internal_only",
            "evidence_type": "cerp_business_snapshot",
            "route_policy": route_policy,
            "evidence_contract": evidence_contract,
            "answer_plan": evidence_contract.get("answer_plan") if isinstance(evidence_contract, dict) else {},
            "controlling_source": {
                "source_family": "cerp_snapshot",
                "source_name": "CERP",
                "source_trace": items[0]["source_trace"] if items else "",
            },
            "query": query,
            "product_query": product_query,
            "requested_fields": requested,
            "field_names": sorted(present_fields),
            "missing_contract_fields": missing_fields if not verified else [],
            "cerp_business_field_discovery": {
                "requested_fields": requested,
                "present_fields": sorted(present_fields),
                "missing_fields": missing_fields,
                "product_count": len(products),
                "verified_unavailable": bool(partial_framework and missing_fields),
            },
            "cerp_results": cerp_results,
            "official_inventory_binding": official_binding,
            "citation_validation": {
                "citation_count": 0,
                "unmapped_citation_count": 0,
                "hard_error_flags": [] if (verified or partial_framework) else ["cerp_field_missing"],
            },
            "hard_error_flags": [] if (verified or partial_framework) else ["cerp_field_missing"],
            "fail_closed_reason": "" if (verified or partial_framework) else "cerp_field_missing",
            "timing": {"generated_at": generated_at},
        }
        return {
            "ok": True,
            "kind": "chat",
            "intent": {"name": "CERP_BUSINESS_LOOKUP"},
            "answer": {"text": answer_text, "citations": [], "metadata": metadata},
            "content": answer_text,
            "language": language,
        }

    @classmethod
    def _product_query(cls, query: str) -> str:
        code_match = re.search(r"\b[A-Z]{2,}[A-Z0-9]*-[A-Z0-9-]{4,}\b", query or "", re.IGNORECASE)
        if code_match:
            return code_match.group(0).strip()
        stripped = QUERY_STOP_RE.sub(" ", query or "")
        stripped = re.sub(r"[\s,;:]+", " ", stripped).strip(" ?.!，。")
        return stripped

    @classmethod
    def _build_items(
        cls,
        products: List[Dict[str, Any]],
        requested_fields: List[str],
        *,
        generated_at: str,
    ) -> Tuple[List[Dict[str, Any]], set[str]]:
        items: List[Dict[str, Any]] = []
        present_fields: set[str] = set()
        for product in products or []:
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            source_trace = str(product.get("source_trace") or f"CERP ExportProduct/ExportProductsInfo | sku:{code} | timestamp:{generated_at}")
            business_fields: Dict[str, Any] = {}
            for field in requested_fields:
                value = cls._field_value(product, field)
                if value not in (None, "", [], {}):
                    business_fields[field] = value
                    present_fields.add(field)
            if not business_fields:
                continue
            proof = {
                "type": "cerp_business",
                "endpoint": "CERP ExportProduct/ExportProductsInfo",
                "code": code,
                "field_names": sorted(business_fields),
                "source_trace": source_trace,
                "timestamp": generated_at,
            }
            items.append(
                {
                    "code": code,
                    "no": code,
                    "name": product.get("name") or product.get("name_en") or product.get("name_ch") or "",
                    "producer": product.get("producer") or "",
                    "vintage": product.get("vintage"),
                    "stock": product.get("stock") or product.get("stock_qty") or product.get("total_stock"),
                    "price": product.get("price") or product.get("list_price"),
                    "list_price": product.get("list_price") or product.get("price"),
                    "vip_price": product.get("vip_price"),
                    "status": product.get("status") or product.get("availability"),
                    "source": "CERP",
                    "source_trace": source_trace,
                    "timestamp": generated_at,
                    "endpoint": "CERP ExportProduct/ExportProductsInfo",
                    "business_fields": business_fields,
                    "field_names": sorted(business_fields),
                    "proof": proof,
                }
            )
        return items, present_fields

    @staticmethod
    def _field_value(product: Dict[str, Any], field: str) -> Any:
        if field == "cost":
            return product.get("cost") if product.get("cost") not in (None, "") else product.get("wholesale_price")
        if field == "margin":
            return product.get("margin")
        if field == "margin_rate":
            return product.get("margin_rate")
        if field == "review_score":
            return product.get("review_score") or product.get("rating")
        return product.get(field)

    @staticmethod
    def _format_field_value(field: str, value: Any) -> str:
        if field == "margin_rate":
            try:
                return f"{float(value) * 100:.2f}%"
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    @staticmethod
    def _should_return_decision_framework(query: str, requested_fields: List[str]) -> bool:
        lowered = str(query or "").casefold()
        if any(field in requested_fields for field in ("order_history", "depletion", "sales_velocity", "allocation")):
            return any(token in lowered for token in ("increase", "maintain", "decrease", "next order", "reorder"))
        return False

    def _build_answer_text(
        self,
        *,
        query: str,
        product_query: str,
        items: List[Dict[str, Any]],
        requested_fields: List[str],
        missing_fields: List[str],
        verified: bool,
        partial_framework: bool = False,
        language: str,
    ) -> str:
        field_list = ", ".join(FIELD_LABELS.get(field, field) for field in requested_fields)
        if not verified:
            if partial_framework:
                return self._build_decision_framework_text(
                    query=query,
                    product_query=product_query,
                    requested_fields=requested_fields,
                    missing_fields=missing_fields,
                    language=language,
                )
            return t(
                "ai.fail_closed.cerp_field_missing",
                language,
                fields=field_list,
                query=product_query or query,
            )
        lines = [t("cerp.business.title", language, count=len(items), fields=field_list)]
        for index, item in enumerate(items[:10], start=1):
            fields = item.get("business_fields") if isinstance(item.get("business_fields"), dict) else {}
            field_text = "; ".join(
                f"{FIELD_LABELS.get(field, field)}: {self._format_field_value(field, value)}"
                for field, value in fields.items()
            )
            name = item.get("name") or item.get("code") or ""
            producer = item.get("producer") or ""
            lines.append(f"{index}. {producer} {name} ({item.get('code')}) - {field_text}".strip())
        if missing_fields:
            lines.append(t("cerp.business.missing_fields", language, fields=", ".join(FIELD_LABELS.get(field, field) for field in missing_fields)))
        return "\n".join(lines)

    @staticmethod
    def _build_decision_framework_text(
        *,
        query: str,
        product_query: str,
        requested_fields: List[str],
        missing_fields: List[str],
        language: str,
    ) -> str:
        requested = ", ".join(FIELD_LABELS.get(field, field) for field in requested_fields)
        missing = ", ".join(FIELD_LABELS.get(field, field) for field in (missing_fields or requested_fields))
        subject = product_query or "[producer]"
        return "\n".join(
            [
                t("chat_templates.sections.verified", language),
                t("chat_templates.business_framework.verified", language, subject=subject, missing=missing),
                t("chat_templates.business_framework.no_invent", language),
                "",
                t("chat_templates.sections.recommendation", language),
                t("chat_templates.business_framework.recommendation_maintain", language),
                t("chat_templates.business_framework.recommendation_increase", language),
                t("chat_templates.business_framework.recommendation_decrease", language),
                "",
                t("chat_templates.sections.missing", language),
                t("chat_templates.business_framework.requested_missing", language, requested=requested),
                t("chat_templates.business_framework.no_next_order", language),
                "",
                t("chat_templates.sections.next_data", language),
                t("chat_templates.business_framework.next_data", language),
            ]
        )
