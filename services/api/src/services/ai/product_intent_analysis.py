from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field

from ...pipelines.llm import openai_client
from .trip_plan import TripPlanService


logger = logging.getLogger(__name__)

_DIRECT_ERP_RE = re.compile(
    r"(?:庫存|現貨|售價|價格|價錢|報價|多少錢|購買|採購|下單|"
    r"\b(?:stock|inventory|price|quote|quotation|buy|purchase|order)\b)",
    re.IGNORECASE,
)
_INVENTORY_RE = re.compile(r"(?:庫存|現貨|\b(?:stock|inventory)\b)", re.IGNORECASE)
_SKU_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9_-]*\d{2,}\b", re.IGNORECASE)
_AMBIGUOUS_RECOMMENDATION_RE = re.compile(
    r"(?:推薦|推介|適合|挑選|選擇|建議(?:哪|什麼)|"
    r"\b(?:recommend|suggest|suitable|choose|pick)\b)",
    re.IGNORECASE,
)
_PRODUCT_NOUN_RE = re.compile(
    r"(?:商品|產品|裝備|器材|用品|帳篷|睡袋|雨衣|背包|頭燈|爐具|釣具|"
    r"\b(?:product|item|gear|equipment|tent|sleeping bag|rain jacket|backpack|headlamp|stove)\b)",
    re.IGNORECASE,
)
_FOLLOWUP_RE = re.compile(
    r"(?:更便宜|便宜一點|不要(?:這個|那個)?品牌|換(?:一個|別的)|其他品牌|"
    r"\b(?:cheaper|lower budget|different brand|exclude that brand|another one)\b)",
    re.IGNORECASE,
)
_OPERATIONAL_KNOWLEDGE_RE = re.compile(
    r"(?:策略|方法|原理|流程|制度|如何管理|如何計算|"
    r"\b(?:strategy|method|principle|process|management|how to calculate)\b)",
    re.IGNORECASE,
)
_CATALOG_QUERY_RE = re.compile(
    r"(?:(?:有哪些|有什麼|列出|清單|列表).{0,10}(?:品牌|型號|商品|產品)|"
    r"(?:品牌|型號|商品|產品).{0,10}(?:有哪些|有什麼|清單|列表)|"
    r"\b(?:what|which|list|show).{0,30}\b(?:brands?|models?|products?|items?)\b)",
    re.IGNORECASE,
)
_LOOKUP_QUERY_CLEANUP_RE = re.compile(
    r"(?:還有多少庫存|庫存還有多少|有多少庫存|有庫存嗎|是否有庫存|庫存(?:量)?|現貨|"
    r"售價|價格|價錢|多少錢|報價|購買|採購|下單|請問|請幫我|幫我|查詢|查一下|"
    r"\b(?:how much (?:stock|inventory)|in stock|stock|inventory|price|quote|quotation|buy|purchase|order|"
    r"please|check|lookup|look up)\b)",
    re.IGNORECASE,
)
_ENGLISH_LOOKUP_STOP_RE = re.compile(
    r"\b(?:what|which|does|do|have|has|is|there|any|the|a|an|of|for|me)\b",
    re.IGNORECASE,
)
_TRACEABLE_BUDGET_RE = re.compile(r"(?:預算|價格|價位|NT\$?|TWD|USD|\$)\s*\d|\d\s*(?:元|塊|TWD|USD)", re.IGNORECASE)
_TRACEABLE_QUANTITY_RE = re.compile(r"\d+\s*(?:個|件|組|套|頂|支|人|pcs?|sets?|people)", re.IGNORECASE)


class ProductNeedProfilePatch(BaseModel):
    activity: Optional[str] = None
    use_case: Optional[str] = None
    location: Optional[str] = None
    duration: Optional[str] = None
    party_size: Optional[int] = Field(default=None, ge=1, le=1000)
    weather: List[str] = Field(default_factory=list)
    budget: Optional[Dict[str, Any]] = None
    categories: List[str] = Field(default_factory=list)
    required_features: List[str] = Field(default_factory=list)
    excluded_features: List[str] = Field(default_factory=list)
    preferred_brands: List[str] = Field(default_factory=list)
    owned_gear: List[str] = Field(default_factory=list)
    quantity: Optional[int] = Field(default=None, ge=1, le=1000)


class ProductIntentPayload(BaseModel):
    task_type: Literal[
        "knowledge",
        "destination_recommendation",
        "destination_filter",
        "product_recommendation",
        "erp_lookup",
    ] = "knowledge"
    decision: Literal["knowledge_only", "knowledge_with_product_bridge", "erp_immediate"]
    confidence: float = Field(ge=0.0, le=1.0)
    need_profile_patch: ProductNeedProfilePatch = Field(default_factory=ProductNeedProfilePatch)
    lookup_operation: Optional[Literal["inventory_lookup", "brand_catalog", "product_lookup"]] = None
    lookup_query: Optional[str] = None


@dataclass(frozen=True)
class ProductIntentDecision:
    task_type: str
    decision: str
    confidence: float
    source: str
    need_profile_patch: Dict[str, Any]
    lookup_operation: Optional[str] = None
    lookup_query: Optional[str] = None

    @property
    def immediate(self) -> bool:
        return self.decision == "erp_immediate"

    @property
    def bridge_eligible(self) -> bool:
        return self.decision in {"knowledge_with_product_bridge", "erp_immediate"}


class ProductIntentAnalysisService:
    """Hybrid ERP intent gate. LLM output may describe needs, never product facts."""

    async def analyze(
        self,
        message: str,
        *,
        history: Optional[Sequence[Dict[str, Any]]] = None,
        context_state: Optional[Dict[str, Any]] = None,
        bridge_eligible: bool = False,
    ) -> ProductIntentDecision:
        text = str(message or "").strip()
        has_prior_product = self._has_prior_product_context(history, context_state)
        explicit_operational_request = bool(
            _DIRECT_ERP_RE.search(text) and not _OPERATIONAL_KNOWLEDGE_RE.search(text)
        )
        if _SKU_RE.search(text) or explicit_operational_request or (has_prior_product and _FOLLOWUP_RE.search(text)):
            task_type = "erp_lookup" if _SKU_RE.search(text) or explicit_operational_request else "product_recommendation"
            if task_type == "erp_lookup":
                operation = self._lookup_operation_from_text(text)
                lookup_query = self._extract_rule_lookup_query(text) or self._latest_erp_lookup_query(
                    history,
                    context_state,
                )
                if not lookup_query:
                    decision = "knowledge_with_product_bridge" if bridge_eligible else "knowledge_only"
                    return ProductIntentDecision("knowledge", decision, 0.0, "fallback", {})
                return ProductIntentDecision(
                    task_type,
                    "erp_immediate",
                    1.0,
                    "rule",
                    {},
                    operation,
                    lookup_query,
                )
            return ProductIntentDecision(task_type, "erp_immediate", 1.0, "rule", {})

        destination_query = TripPlanService.is_destination_query(text)
        destination_followup = bool(
            TripPlanService.has_trip_context(TripPlanService.from_context(context_state))
            and TripPlanService.is_destination_filter(text)
        )
        catalog_query = bool(_CATALOG_QUERY_RE.search(text))
        if not (_AMBIGUOUS_RECOMMENDATION_RE.search(text) or catalog_query or destination_query or destination_followup):
            decision = "knowledge_with_product_bridge" if bridge_eligible else "knowledge_only"
            return ProductIntentDecision("knowledge", decision, 1.0, "rule", {})

        try:
            payload = await asyncio.wait_for(
                self._classify_with_llm(text, history=history, context_state=context_state),
                timeout=8.0,
            )
            patch = self._sanitize_patch(payload.need_profile_patch.model_dump(), text)
            decision = payload.decision
            task_type = payload.task_type
            lookup_operation: Optional[str] = None
            lookup_query: Optional[str] = None
            if task_type in {"destination_recommendation", "destination_filter"}:
                decision = "knowledge_only"
            elif decision == "erp_immediate" and task_type not in {"product_recommendation", "erp_lookup"}:
                decision = "knowledge_with_product_bridge" if bridge_eligible else "knowledge_only"
            elif task_type == "erp_lookup":
                lookup_operation = payload.lookup_operation
                lookup_query = self._sanitize_lookup_query(payload.lookup_query, text)
                if decision != "erp_immediate" or not lookup_operation or not lookup_query:
                    task_type = "knowledge"
                    decision = "knowledge_with_product_bridge" if bridge_eligible else "knowledge_only"
                    lookup_operation = None
                    lookup_query = None
            return ProductIntentDecision(
                task_type,
                decision,
                payload.confidence,
                "llm",
                patch,
                lookup_operation,
                lookup_query,
            )
        except Exception as exc:
            logger.info("Product intent LLM classification fell back safely: %s", exc)
            decision = "knowledge_with_product_bridge" if bridge_eligible else "knowledge_only"
            task_type = self._fallback_task_type(text, context_state)
            if task_type in {"destination_recommendation", "destination_filter"}:
                decision = "knowledge_only"
            return ProductIntentDecision(task_type, decision, 0.0, "fallback", {})

    async def _classify_with_llm(
        self,
        message: str,
        *,
        history: Optional[Sequence[Dict[str, Any]]],
        context_state: Optional[Dict[str, Any]],
    ) -> ProductIntentPayload:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not configured")
        recent = []
        for item in list(history or [])[-12:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if content:
                recent.append({"role": str(item.get("role") or "user"), "content": content[:600]})
        saved_profile = {}
        if isinstance(context_state, dict) and isinstance(context_state.get("product_need_profile"), dict):
            saved_profile = dict(context_state["product_need_profile"])
        saved_trip_plan = {}
        if isinstance(context_state, dict) and isinstance(context_state.get("trip_plan"), dict):
            saved_trip_plan = dict(context_state["trip_plan"])
        system = (
            "Classify the current task and whether it requires YS ERP product facts. "
            "Use destination_recommendation for campsite/place suggestions and destination_filter for refining those places. "
            "Destination tasks are knowledge_only and must never use ERP. "
            "Use erp_immediate only when the user asks for actual products/equipment, inventory, price, quote, or purchase. "
            "Use erp_lookup for factual ERP catalog questions. Set lookup_operation to inventory_lookup for stock, "
            "brand_catalog for brands in a requested category, or product_lookup for product/model/price lists. "
            "For erp_lookup, lookup_query must be an exact contiguous subject copied from the current message; "
            "never translate, expand, or invent it. For example, '目前釣竿品牌有哪些？' uses brand_catalog and query '釣竿'. "
            "An explicit request for products or equipment is an ERP request even without price or inventory wording: "
            "'推薦玉山雨季裝備' and '直接推薦玉山雨季裝備' are product_recommendation with erp_immediate. "
            "When saved_trip_plan is present and the user asks for suitable supplies, gear, or equipment recommendations, "
            "including a short follow-up such as '合適的用品推薦', classify it as product_recommendation with erp_immediate. "
            "By contrast, '玉山雨季如何準備？' asks for preparation advice and is knowledge_with_product_bridge. "
            "A request for advice, methods, places, learning resources, or how to prepare is knowledge_only or "
            "knowledge_with_product_bridge even if it contains the word recommend. "
            "Extract only need fields supported by the current message or supplied context. Unknown fields stay null/empty. "
            "Never output SKU, product name, price, stock, or availability. Return only the required JSON object."
        )
        user = json.dumps(
            {
                "message": message,
                "recent_history": recent,
                "saved_need_profile": saved_profile,
                "saved_trip_plan": saved_trip_plan,
            },
            ensure_ascii=False,
        )
        schema = ProductIntentPayload.model_json_schema()
        raw = await openai_client.chat_complete(
            system=system,
            user=user,
            history=[{"role": "user", "content": user}],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "product_intent", "strict": False, "schema": schema},
            },
        )
        return ProductIntentPayload.model_validate(self._parse_json(raw))

    @staticmethod
    def _parse_json(value: str) -> Dict[str, Any]:
        text = str(value or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Product intent response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Product intent response must be an object")
        return parsed

    @staticmethod
    def _sanitize_patch(patch: Dict[str, Any], message: str) -> Dict[str, Any]:
        cleaned = {key: value for key, value in patch.items() if value not in (None, "", [], {})}
        if "budget" in cleaned and not _TRACEABLE_BUDGET_RE.search(message):
            cleaned.pop("budget", None)
        if "quantity" in cleaned and not _TRACEABLE_QUANTITY_RE.search(message):
            cleaned.pop("quantity", None)
        if "party_size" in cleaned and not re.search(r"\d+\s*(?:人|people|persons?)", message, re.IGNORECASE):
            cleaned.pop("party_size", None)
        for key in ("preferred_brands", "excluded_features", "owned_gear"):
            values = cleaned.get(key)
            if isinstance(values, list):
                cleaned[key] = [value for value in values if str(value).casefold() in message.casefold()]
                if not cleaned[key]:
                    cleaned.pop(key, None)
        return cleaned

    @staticmethod
    def _lookup_operation_from_text(message: str) -> str:
        return "inventory_lookup" if _INVENTORY_RE.search(str(message or "")) else "product_lookup"

    @staticmethod
    def _extract_rule_lookup_query(message: str) -> Optional[str]:
        text = str(message or "").strip()
        sku = _SKU_RE.search(text)
        if sku:
            return sku.group(0)
        candidate = _LOOKUP_QUERY_CLEANUP_RE.sub(" ", text)
        candidate = _ENGLISH_LOOKUP_STOP_RE.sub(" ", candidate)
        candidate = re.sub(r"(?:還有多少|還有|還|是多少|為多少|目前|現在|即時|的|嗎|呢|？|\?)", " ", candidate)
        candidate = re.sub(r"[\s,;:，。！!]+", " ", candidate).strip()
        if not candidate or candidate.casefold() == text.casefold():
            return None
        return ProductIntentAnalysisService._sanitize_lookup_query(candidate, text)

    @staticmethod
    def _sanitize_lookup_query(value: Any, message: str) -> Optional[str]:
        query = re.sub(r"[\s,;:，。！？!?]+", " ", str(value or "")).strip()
        source = str(message or "")
        if not query or query.casefold() not in source.casefold():
            return None
        if query.casefold() in {
            "品牌",
            "型號",
            "商品",
            "產品",
            "brand",
            "brands",
            "model",
            "models",
            "product",
            "products",
        }:
            return None
        return query

    @staticmethod
    def _latest_erp_lookup_query(
        history: Optional[Sequence[Dict[str, Any]]],
        context_state: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        if isinstance(context_state, dict):
            saved_lookup = context_state.get("erp_lookup")
            if isinstance(saved_lookup, dict):
                query = str(saved_lookup.get("query") or "").strip()
                if query:
                    return query
        for item in reversed(list(history or [])):
            metadata = item.get("metadata") if isinstance(item, dict) else None
            if not isinstance(metadata, dict):
                continue
            lookup = metadata.get("erp_lookup")
            if isinstance(lookup, dict):
                query = str(lookup.get("query") or "").strip()
                if query:
                    return query
            results = metadata.get("product_results")
            if isinstance(results, list):
                for product in results:
                    if not isinstance(product, dict):
                        continue
                    sku = str(product.get("sku") or product.get("no") or "").strip()
                    if sku:
                        return sku
        return None

    @staticmethod
    def _has_prior_product_context(
        history: Optional[Sequence[Dict[str, Any]]],
        context_state: Optional[Dict[str, Any]],
    ) -> bool:
        if isinstance(context_state, dict) and ProductIntentAnalysisService._has_profile_values(
            context_state.get("product_need_profile")
        ):
            return True
        for item in reversed(list(history or [])):
            metadata = item.get("metadata") if isinstance(item, dict) else None
            if not isinstance(metadata, dict):
                continue
            if metadata.get("product_results"):
                return True
            bridge = metadata.get("product_bridge")
            if isinstance(bridge, dict) and bridge.get("eligible") and ProductIntentAnalysisService._has_profile_values(
                bridge.get("need_profile")
            ):
                return True
        return False

    @staticmethod
    def _has_profile_values(value: Any) -> bool:
        return isinstance(value, dict) and any(item not in (None, "", [], {}) for item in value.values())

    @staticmethod
    def _fallback_task_type(message: str, context_state: Optional[Dict[str, Any]]) -> str:
        text = str(message or "")
        if TripPlanService.is_destination_query(text):
            return "destination_filter" if TripPlanService.is_destination_filter(text) else "destination_recommendation"
        plan = TripPlanService.from_context(context_state)
        if TripPlanService.has_trip_context(plan) and TripPlanService.is_destination_filter(text):
            return "destination_filter"
        return "knowledge"


def merge_need_profile_patch(
    profile: Dict[str, Any],
    patch: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    merged = dict(profile or {})
    for key, value in (patch or {}).items():
        if key in {"weather", "categories", "required_features", "excluded_features", "preferred_brands", "owned_gear"}:
            existing = list(merged.get(key) or [])
            seen = {str(item).casefold() for item in existing}
            for item in value if isinstance(value, list) else []:
                normalized = str(item or "").strip()
                if normalized and normalized.casefold() not in seen:
                    existing.append(normalized)
                    seen.add(normalized.casefold())
            merged[key] = existing
        elif value not in (None, "", [], {}):
            merged[key] = value
    return merged
