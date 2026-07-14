from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..core.i18n import t
from ..pipelines.llm.openai_client import OpenAIChatHTTPError, chat_complete
from ..utils.quote_search import (
    build_quote_match_summary,
    has_quote_semantic_filters,
    normalize_quote_input_text,
    parse_quote_search_criteria,
    quote_product_alternative_score,
    quote_product_matches_criteria,
)
from ..utils.inventory_intent import is_generic_inventory_listing_query
from .ai.answer_route_policy import build_answer_route_policy
from .ai.evidence_contracts import build_cerp_evidence_contract
from .cerp_service import CerpService

logger = logging.getLogger(__name__)


_RESULT_LIMIT_RE = re.compile(
    r"(\d+)\s*(?:款|支|瓶|項|酒款|wines?|bottles?|items?)",
    re.IGNORECASE,
)
_CERP_RECOMMENDATION_RE = re.compile(
    r"(?:cerp|庫存|現貨|有庫存|有貨|可售|stock|inventory|availability|available|sellable|unavailable|reserved|carry|carried|in\s+our\s+data)",
    re.IGNORECASE,
)
_RECOMMENDATION_RE = re.compile(
    r"(?:推薦|建議|列出|找|show|list|recommend|find|which|what|carry)",
    re.IGNORECASE,
)
_COMMERCIAL_FILTER_RE = re.compile(
    r"(?:under|below|less\s+than|at\s+least|over|exclude|price|retail|vip|NT\$|\$|\d+\s*bottles?)",
    re.IGNORECASE,
)
_WINE_STYLE_RE = re.compile(
    r"(?:champagne|burgundy|bourgogne|côte|cote|chablis|beaune|nuits|beaujolais|puligny|meursault|vosne|wine|wines?|香檳|香槟|勃艮第|布根地|酒款)",
    re.IGNORECASE,
)
_STOCK_RE = re.compile(
    r"(?:有庫存|現貨|有貨|可售|in[\s-]?stock|with\s+stock|available|currently\s+available|sellable)",
    re.IGNORECASE,
)

_WINE_PRODUCT_REQUEST_RE = re.compile(
    r"(?:wine|wines?|champagne|burgundy|bourgogne|chablis|puligny|meursault|vosne|bottle|bottles|酒款|葡萄酒|香檳|勃根地)",
    re.IGNORECASE,
)
_NON_WINE_PRODUCT_RE = re.compile(
    r"(?:zalto|glass(?:es)?|decanter|stopper|cork(?:screw)?|opener|book|guide|magazine|accessor(?:y|ies)|wine\s*key|酒杯|杯|醒酒器|瓶塞|開瓶|開酒|書|雜誌)",
    re.IGNORECASE,
)


_BUILD_CASE_RE = re.compile(
    r"\b(?:build|assemble|create)\b.*\b(?:case|bottle|bottles|wine|wines|champagne)\b",
    re.IGNORECASE,
)
_HYPHENATED_BOTTLE_LIMIT_RE = re.compile(r"\b(\d+)\s*[- ]?\s*bottles?\b", re.IGNORECASE)
_RECOMMEND_COUNT_RE = re.compile(
    r"\b(?:recommend|list|show|find|select|pick)\s+(\d+)\b",
    re.IGNORECASE,
)
_UNBOUNDED_LISTING_RE = re.compile(
    r"(?:\b(?:all|list\s+all|find\s+all|show\s+all)\b|所有|全部|全品項|找出|列出)",
    re.IGNORECASE,
)
_EXACT_FACT_QUERY_RE = re.compile(
    r"(?:\b(?:do\s+we|are\s+we|currently|now)\b.{0,80}\b(?:carry|sell|have)\b|"
    r"\b(?:carry|carried|stock|sell|available|availability)\b.{0,80}\b(?:if\s+yes|if\s+no|say\s+no)\b|"
    r"是否.{0,30}(?:有|販售|銷售|庫存)|有沒有.{0,30}(?:庫存|現貨|販售))",
    re.IGNORECASE,
)
_FACT_CLAUSE_RE = re.compile(r"\b(?:if\s+yes|if\s+no|give\s+sku|say\s+no)\b.*$", re.IGNORECASE)
_STOCK_MIN_QUERY_RE = re.compile(r"(?:at\s+least|>=|至少)\s*([0-9]+)\s*(?:bottles?|瓶|支)?", re.IGNORECASE)
_TEXT_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)
_OUTDOOR_RECOMMENDATION_TOPIC_RE = re.compile(
    r"(?:\u7389\u5c71|\u77f3\u9580\u5c71|[\u4e00-\u9fff]{1,8}\u5c71|\u767b\u5c71|\u5065\u884c|\u9732\u71df|\u91e3\u9b5a|\u6236\u5916|"
    r"hiking|trekking|mountain|camping|fishing|outdoor)",
    re.IGNORECASE,
)
_OUTDOOR_PRODUCT_REQUEST_RE = re.compile(
    r"(?:\u5217\u51fa|\u63a8\u85a6|\u5efa\u8b70|\u6e96\u5099|\u9700\u8981|\u54ea\u4e9b|\u6e05\u55ae|recommend|suggest|prepare|need|list|checklist).{0,24}"
    r"(?:\u88dd\u5099|\u5668\u6750|\u5546\u54c1|\u7522\u54c1|\u7528\u54c1|gear|equipment|product|item|tackle)"
    r"|(?:\u88dd\u5099|\u5668\u6750|\u5546\u54c1|\u7522\u54c1|\u7528\u54c1|gear|equipment|product|item|tackle).{0,24}"
    r"(?:\u63a8\u85a6|\u5efa\u8b70|\u6e96\u5099|\u9700\u8981|\u6e05\u55ae|recommend|suggest|prepare|need|list|checklist)",
    re.IGNORECASE,
)
_OUTDOOR_BUSINESS_RE = re.compile(
    r"(?:\u5eab\u5b58|\u73fe\u8ca8|\u6709\u8ca8|\u50f9\u683c|\u50f9\u9322|\u5831\u50f9|vip|sku|"
    r"inventory|stock|in[\s-]?stock|price|quote|quotation)",
    re.IGNORECASE,
)
_OUTDOOR_CATEGORY_PLANS = {
    "hiking": [
        ("backpack_storage", {"zh-Hant": "\u80cc\u5305/\u6536\u7d0d", "en": "Backpack / storage", "ja": "\u30d0\u30c3\u30af\u30d1\u30c3\u30af/\u53ce\u7d0d"}, ("backpack", "bag", "pack", "storage", "organizer", "\u80cc\u5305", "\u6536\u7d0d", "\u5305", "\u7bb1")),
        ("rain_protection", {"zh-Hant": "\u96e8\u5177/\u9632\u6c34", "en": "Rain / waterproofing", "ja": "\u96e8\u5177/\u9632\u6c34"}, ("rain", "waterproof", "poncho", "tarp", "cover", "\u96e8", "\u9632\u6c34", "\u5929\u5e55")),
        ("lighting", {"zh-Hant": "\u7167\u660e", "en": "Lighting", "ja": "\u7167\u660e"}, ("lantern", "headlamp", "light", "\u71df\u71c8", "\u982d\u71c8", "\u7167\u660e", "\u71c8")),
        ("warmth_sleep", {"zh-Hant": "\u4fdd\u6696/\u7761\u7720", "en": "Warmth / sleep", "ja": "\u9632\u5bd2/\u7761\u7720"}, ("sleeping bag", "sleeping pad", "mat", "blanket", "warm", "\u7761\u888b", "\u7761\u588a", "\u4fdd\u6696")),
        ("cookware_water", {"zh-Hant": "\u708a\u5177/\u6c34\u5177", "en": "Cooking / water", "ja": "\u8abf\u7406/\u6c34\u307e\u308f\u308a"}, ("stove", "burner", "cookset", "kettle", "bottle", "water", "\u7210", "\u708a", "\u934b", "\u6c34")),
        ("safety_repair", {"zh-Hant": "\u5b89\u5168/\u7dad\u4fee", "en": "Safety / repair", "ja": "\u5b89\u5168/\u4fee\u7406"}, ("repair", "kit", "rope", "cord", "carabiner", "tool", "\u7dad\u4fee", "\u5b89\u5168", "\u7e69", "\u5de5\u5177")),
    ],
    "camping": [
        ("shelter", {"zh-Hant": "\u5e33\u7bf7/\u5929\u5e55", "en": "Shelter", "ja": "\u30c6\u30f3\u30c8/\u30bf\u30fc\u30d7"}, ("tent", "tarp", "shelter", "canopy", "\u5e33\u7bf7", "\u5929\u5e55")),
        ("sleep", {"zh-Hant": "\u7761\u7720\u7cfb\u7d71", "en": "Sleep system", "ja": "\u30b9\u30ea\u30fc\u30d7\u30b7\u30b9\u30c6\u30e0"}, ("sleeping bag", "sleeping pad", "mat", "cot", "\u7761\u888b", "\u7761\u588a")),
        ("lighting", {"zh-Hant": "\u7167\u660e", "en": "Lighting", "ja": "\u7167\u660e"}, ("lantern", "headlamp", "light", "\u71df\u71c8", "\u982d\u71c8", "\u71c8")),
        ("cookware", {"zh-Hant": "\u7210\u5177/\u708a\u5177", "en": "Stove / cookware", "ja": "\u30b9\u30c8\u30fc\u30d6/\u8abf\u7406\u5668\u5177"}, ("stove", "burner", "cookset", "kettle", "grill", "\u7210", "\u708a", "\u934b")),
        ("furniture_storage", {"zh-Hant": "\u684c\u6905/\u6536\u7d0d", "en": "Furniture / storage", "ja": "\u30d5\u30a1\u30cb\u30c1\u30e3\u30fc/\u53ce\u7d0d"}, ("chair", "table", "storage", "box", "bag", "\u6905", "\u684c", "\u6536\u7d0d")),
        ("power_safety", {"zh-Hant": "\u96fb\u6e90/\u5b89\u5168", "en": "Power / safety", "ja": "\u96fb\u6e90/\u5b89\u5168"}, ("power", "solar", "repair", "kit", "tool", "\u96fb\u6e90", "\u592a\u967d\u80fd", "\u7dad\u4fee", "\u5de5\u5177")),
    ],
    "fishing": [
        ("line_leader", {"zh-Hant": "\u7dda\u6750/\u524d\u5c0e\u7dda", "en": "Line / leader", "ja": "\u30e9\u30a4\u30f3/\u30ea\u30fc\u30c0\u30fc"}, ("line", "leader", "pe", "fc", "\u7dda", "\u524d\u5c0e")),
        ("lure", {"zh-Hant": "\u8def\u4e9e/\u64ec\u990c", "en": "Lure", "ja": "\u30eb\u30a2\u30fc"}, ("lure", "jig", "popper", "minnow", "slim", "\u8def\u4e9e", "\u64ec\u990c")),
        ("hook_rig", {"zh-Hant": "\u9264/\u914d\u4ef6", "en": "Hooks / rigs", "ja": "\u30d5\u30c3\u30af/\u4ed5\u639b\u3051"}, ("hook", "ring", "snap", "sinker", "peg", "\u9264", "\u74b0", "\u925b")),
        ("rod_reel", {"zh-Hant": "\u7aff/\u6372\u7dda\u5668", "en": "Rod / reel", "ja": "\u30ed\u30c3\u30c9/\u30ea\u30fc\u30eb"}, ("rod", "reel", "\u7aff", "\u6372\u7dda")),
        ("storage_tool", {"zh-Hant": "\u6536\u7d0d/\u5de5\u5177", "en": "Storage / tools", "ja": "\u53ce\u7d0d/\u30c4\u30fc\u30eb"}, ("box", "case", "bag", "tool", "clip", "\u6536\u7d0d", "\u7bb1", "\u5de5\u5177")),
    ],
}
_EXACT_FACT_STOPWORDS = {
    "do", "we", "currently", "current", "carry", "carried", "sell", "have", "stock", "inventory",
    "available", "availability", "if", "yes", "no", "give", "sku", "and", "say", "now", "the",
    "a", "an", "in", "cerp", "ys_ai",
}
_ANSWER_LIST_DISPLAY_LIMIT = 50
_ALL_MATCHING_CANDIDATE_LIMIT = 200


class CerpRecommendationService:
    """Shared CERP recommendation path for normal chat and quote-like inventory requests."""

    def __init__(self, cerp_service: Optional[CerpService] = None) -> None:
        self._cerp_service = cerp_service or CerpService()

    @classmethod
    def should_handle(cls, query: str) -> bool:
        text = str(query or "").strip()
        if not text:
            return False
        if is_generic_inventory_listing_query(text):
            return True
        if cls._is_outdoor_product_recommendation_query(text):
            return True
        if cls._query_mode(text) == "exact_inventory_fact_check":
            return True
        if _BUILD_CASE_RE.search(text) and (
            _WINE_STYLE_RE.search(text)
            or _CERP_RECOMMENDATION_RE.search(text)
            or "inventory" in text.casefold()
        ):
            return True
        if _CERP_RECOMMENDATION_RE.search(text) and _RECOMMENDATION_RE.search(text):
            return True
        return bool(
            _WINE_STYLE_RE.search(text)
            and _RECOMMENDATION_RE.search(text)
            and (_STOCK_RE.search(text) or _COMMERCIAL_FILTER_RE.search(text))
        )

    async def recommend(
        self,
        query: str,
        *,
        language: str = "zh-Hant",
        rag_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_query = normalize_quote_input_text(query)
        recommendation_groups: List[Dict[str, Any]] = []
        if is_generic_inventory_listing_query(normalized_query):
            query_mode = "generic_inventory_listing"
            result_limit = 20
            criteria = {
                "query_mode": query_mode,
                "stock_policy": "in_stock_only",
                "result_limit": result_limit,
                "query_variants": [normalized_query],
            }
            candidates = await self._cerp_service.fetch_top_stock_products(
                limit=result_limit,
                allow_zero_stock=False,
                raise_on_error=True,
            )
            selected = [dict(item) for item in candidates[:result_limit]]
            exact_items = [dict(item) for item in selected]
            alternatives: List[Dict[str, Any]] = []
        elif self._is_outdoor_product_recommendation_query(normalized_query):
            query_mode = "outdoor_product_recommendation"
            result_limit = 15
            categories = self._outdoor_categories_for_query(normalized_query)
            criteria = {
                "query_mode": query_mode,
                "stock_policy": "in_stock_only",
                "result_limit": result_limit,
                "query_variants": [normalized_query],
                "recommendation_categories": [
                    {"id": category_id, "label": labels.get(language) or labels.get("en") or category_id}
                    for category_id, labels, _keywords in categories
                ],
            }
            candidates = await self._cerp_service.fetch_top_stock_products(
                limit=200,
                allow_zero_stock=False,
                raise_on_error=True,
            )
            selected = self._select_outdoor_recommendation_products(
                normalized_query,
                candidates,
                categories=categories,
                language=language,
                limit=result_limit,
            )
            recommendation_groups = await self._apply_llm_recommendation_groups(
                normalized_query,
                selected,
                language=language,
                rag_context=rag_context,
            )
            exact_items = [dict(item) for item in selected]
            alternatives = []
        else:
            quote_request = self._build_quote_request(normalized_query)
            query_mode = str(quote_request.get("query_mode") or self._query_mode(normalized_query))
            criteria = parse_quote_search_criteria(
                normalized_query,
                quote_request=quote_request,
                query_variants=[normalized_query],
            )
            criteria = self._cleanup_criteria(normalized_query, criteria)
            if query_mode == "exact_inventory_fact_check":
                criteria = self._apply_exact_fact_terms(normalized_query, criteria)
            result_limit = self._resolve_result_limit(criteria, quote_request, query_mode)
            candidate_limit = self._candidate_limit_for_mode(result_limit, query_mode)
            candidates = await self._cerp_service.search_quote_candidates(
                normalized_query,
                query_variants=criteria.get("query_variants") or [normalized_query],
                limit=candidate_limit,
                page_size=min(max(candidate_limit, 24), 50),
                desired_quantity=1,
                quote_criteria=criteria,
                max_pages_per_term=4 if query_mode == "unbounded_inventory_listing" else 1,
                raise_on_error=True,
            )
            selected, exact_items, alternatives = self._select_products(
                candidates,
                criteria,
                result_limit,
                query=normalized_query,
                query_mode=query_mode,
                allow_alternatives=query_mode == "bounded_recommendation",
            )
        if query_mode != "outdoor_product_recommendation":
            recommendation_groups = []
        selected_for_answer = selected[:_ANSWER_LIST_DISPLAY_LIMIT]
        generated_at = datetime.now(timezone.utc).isoformat()
        answer_text = self._build_answer_text(
            query=normalized_query,
            products=selected_for_answer,
            criteria=criteria,
            language=language,
            query_mode=query_mode,
            total_count=len(selected),
            displayed_count=len(selected_for_answer),
            result_truncated=len(selected) > len(selected_for_answer),
        )
        cerp_results = self._build_cerp_results(
            selected,
            generated_at=generated_at,
            total_match_count=len(selected),
            displayed_count=len(selected_for_answer),
            result_truncated=len(selected) > len(selected_for_answer),
            query_mode=query_mode,
        )
        citations = self._build_citations(cerp_results)
        if query_mode == "exact_inventory_fact_check" and not selected:
            citations = [self._build_absence_citation(normalized_query, criteria, generated_at)]
        route_policy = build_answer_route_policy(
            prompt_category="quote_recommendation",
            intent_name="QUOTE_LIST",
            entity_hints={},
            context_state={},
            source_policy="internal_only",
        )
        evidence_contract = build_cerp_evidence_contract(
            cerp_products=selected,
            prompt_category="quote_recommendation",
            source_policy="internal_only",
            route_policy=route_policy,
        )
        official_binding = {
            "required": True,
            "proof_count": len(cerp_results["items"]),
            "proofs": [item["proof"] for item in cerp_results["items"]],
            "source": "CERP",
            "timestamp": generated_at,
            "query_mode": query_mode,
            "verified_absence": query_mode == "exact_inventory_fact_check" and not selected,
        }
        outdoor_no_products = query_mode == "outdoor_product_recommendation" and not selected
        if outdoor_no_products and isinstance(evidence_contract, dict):
            evidence_contract["status"] = "partial_pass"
            evidence_contract["partial_pass_reason"] = "outdoor_recommendation_without_cerp_products"
            evidence_contract["missing_contract_fields"] = ["cerp_results"]
        verified = bool(selected) or query_mode == "exact_inventory_fact_check" or outdoor_no_products
        hard_flags = [] if verified else ["cerp_recommendation_no_results"]
        metadata = {
            "intent": "QUOTE_LIST",
            "prompt_category": "quote_recommendation",
            "answer_mode": "cerp_recommendation" if not outdoor_no_products else "outdoor_llm_no_cerp_products",
            "answer_verification_mode": "verified_answer" if bool(selected) else ("partial_answer_with_gaps" if outdoor_no_products else "data_or_permission_needed"),
            "answer_verification": {
                "mode": "verified_answer" if bool(selected) else ("partial_answer_with_gaps" if outdoor_no_products else "data_or_permission_needed"),
                "verified": bool(selected) or query_mode == "exact_inventory_fact_check",
                "requires_disclaimer": outdoor_no_products,
                "reason": (
                    "cerp_exact_absence_verified"
                    if query_mode == "exact_inventory_fact_check" and not selected
                    else "cerp_snapshot_proof" if selected else "outdoor_recommendation_without_cerp_products" if outdoor_no_products else "cerp_recommendation_no_results"
                ),
            },
            "response_mode": "cerp_recommendation" if not outdoor_no_products else "outdoor_llm_no_cerp_products",
            "substantive_answer": verified,
            "source_policy": "internal_only",
            "evidence_type": "cerp_snapshot",
            "route_policy": route_policy,
            "evidence_contract": evidence_contract,
            "answer_plan": evidence_contract.get("answer_plan") if isinstance(evidence_contract, dict) else {},
            "controlling_source": {
                "source_family": "cerp_snapshot",
                "source_name": "CERP",
                "source_trace": cerp_results["items"][0]["source_trace"] if cerp_results["items"] else "",
            },
            "query": normalized_query,
            "requested_filters": criteria,
            "search_criteria": criteria,
            "cerp_query_mode": query_mode,
            "recommendation_groups": recommendation_groups,
            "rag_optional": query_mode == "outdoor_product_recommendation",
            "rag_context_used": bool((rag_context or {}).get("hit_count")),
            "rag_hit_count": int((rag_context or {}).get("hit_count") or 0),
            "all_matching": query_mode == "unbounded_inventory_listing",
            "result_limit": result_limit,
            "result_truncated": len(selected) > len(selected_for_answer),
            "total_match_count": len(selected),
            "displayed_count": len(selected_for_answer),
            "limit_reason": "answer_text_display_limit" if len(selected) > len(selected_for_answer) else "",
            "quote_items": selected,
            "exact_quote_items": exact_items,
            "recommended_alternatives": alternatives if query_mode == "bounded_recommendation" else [],
            "near_matches_suppressed_count": 0 if query_mode == "bounded_recommendation" else len(alternatives),
            "cerp_results": cerp_results,
            "official_inventory_binding": official_binding,
            "citation_validation": {
                "citation_count": len(citations),
                "unmapped_citation_count": 0,
                "hard_error_flags": [],
            },
            "hard_error_flags": hard_flags,
            "fail_closed_reason": "" if verified else "cerp_recommendation_no_results",
            "match_summary": build_quote_match_summary(
                criteria,
                exact_count=len(exact_items),
                alternative_count=len(alternatives) if query_mode == "bounded_recommendation" else 0,
            ),
            "timing": {"generated_at": generated_at},
        }
        return {
            "ok": True,
            "kind": "chat",
            "intent": {"name": "QUOTE_LIST"},
            "answer": {
                "text": answer_text,
                "citations": citations,
                "metadata": metadata,
            },
            "content": answer_text,
            "language": language,
        }

    @staticmethod
    def _build_quote_request(query: str) -> Dict[str, Any]:
        query_mode = CerpRecommendationService._query_mode(query)
        limit: Optional[int] = None if query_mode in {"exact_inventory_fact_check", "unbounded_inventory_listing"} else 5
        if query_mode != "unbounded_inventory_listing":
            match = _RESULT_LIMIT_RE.search(query or "")
            if not match:
                match = _HYPHENATED_BOTTLE_LIMIT_RE.search(query or "")
            if not match:
                match = _RECOMMEND_COUNT_RE.search(query or "")
            if match:
                try:
                    limit = max(1, min(int(match.group(1)), 20))
                except (TypeError, ValueError):
                    limit = 5 if query_mode == "bounded_recommendation" else None
        lowered = str(query or "").casefold()
        stock_policy = "in_stock_only" if (_STOCK_RE.search(query or "") or "inventory" in lowered) else "stock_first"
        return {
            "result_limit": limit,
            "line_item_quantity": 1,
            "stock_policy": stock_policy,
            "query_mode": query_mode,
            "all_matching": query_mode == "unbounded_inventory_listing",
        }

    @staticmethod
    def _query_mode(query: str) -> str:
        text = str(query or "").strip()
        lowered = text.casefold()
        has_explicit_count = bool(
            _RESULT_LIMIT_RE.search(text)
            or _HYPHENATED_BOTTLE_LIMIT_RE.search(text)
            or _RECOMMEND_COUNT_RE.search(text)
        )
        if _EXACT_FACT_QUERY_RE.search(text) and re.search(r"\b(?:19|20)\d{2}\b", text):
            return "exact_inventory_fact_check"
        if _UNBOUNDED_LISTING_RE.search(text) and not has_explicit_count:
            return "unbounded_inventory_listing"
        if re.search(r"\b(?:list|find|show)\s+all\b", lowered):
            return "unbounded_inventory_listing"
        return "bounded_recommendation"

    @staticmethod
    def _is_outdoor_product_recommendation_query(query: str) -> bool:
        text = str(query or "").strip()
        if not text:
            return False
        return bool(
            _OUTDOOR_RECOMMENDATION_TOPIC_RE.search(text)
            and _OUTDOOR_PRODUCT_REQUEST_RE.search(text)
        )

    @staticmethod
    def _outdoor_categories_for_query(query: str) -> List[Tuple[str, Dict[str, str], Tuple[str, ...]]]:
        text = str(query or "").casefold()
        if re.search(r"\u91e3\u9b5a|fishing|tackle", text, flags=re.IGNORECASE):
            return list(_OUTDOOR_CATEGORY_PLANS["fishing"])
        if re.search(r"\u9732\u71df|camping|camp", text, flags=re.IGNORECASE):
            return list(_OUTDOOR_CATEGORY_PLANS["camping"])
        return list(_OUTDOOR_CATEGORY_PLANS["hiking"])

    @staticmethod
    def _product_search_text(product: Dict[str, Any]) -> str:
        return " ".join(
            str(product.get(key) or "")
            for key in (
                "no",
                "code",
                "id",
                "producer",
                "brand",
                "supplier",
                "name",
                "name_en",
                "name_ch",
                "product_name",
                "vintage",
                "spec",
                "spec1",
                "model",
                "model_year",
                "region",
                "category",
                "type",
                "wine_type",
                "wine_class",
                "material",
                "alcohol",
                "size",
                "color",
                "rating",
                "bundle",
            )
        ).casefold()

    @classmethod
    def _select_outdoor_recommendation_products(
        cls,
        query: str,
        candidates: List[Dict[str, Any]],
        *,
        categories: List[Tuple[str, Dict[str, str], Tuple[str, ...]]],
        language: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        selected_codes = set()
        per_category = 2
        for category_id, labels, keywords in categories:
            category_label = labels.get(language) or labels.get("en") or category_id
            ranked: List[Tuple[float, Dict[str, Any], List[str]]] = []
            for candidate in candidates or []:
                if not isinstance(candidate, dict):
                    continue
                code = str(candidate.get("no") or candidate.get("code") or candidate.get("id") or "").strip()
                if code and code in selected_codes:
                    continue
                text = cls._product_search_text(candidate)
                matched = [keyword for keyword in keywords if str(keyword).casefold() in text]
                if not matched:
                    continue
                stock = cls._stock_value(candidate)
                if stock <= 0:
                    continue
                price = cls._price_value(candidate, None) or 0.0
                score = (len(matched) * 100.0) + min(stock, 100) + (1.0 if price else 0.0)
                ranked.append((score, candidate, matched))
            ranked.sort(key=lambda item: (item[0], cls._stock_value(item[1])), reverse=True)
            for _score, candidate, matched in ranked[:per_category]:
                normalized = dict(candidate)
                normalized["recommendation_category"] = category_id
                normalized["category"] = normalized.get("category") or category_label
                normalized["recommendation_category_label"] = category_label
                normalized["match_keywords"] = matched[:6]
                normalized["recommendation_reason"] = cls._outdoor_recommendation_reason(
                    query,
                    normalized,
                    category_label=category_label,
                    matched_keywords=matched,
                    language=language,
                )
                normalized["reason"] = normalized["recommendation_reason"]
                normalized.setdefault("source", "CERP")
                normalized.setdefault("source_trace", cls._source_trace(normalized))
                selected.append(normalized)
                code = str(normalized.get("no") or normalized.get("code") or normalized.get("id") or "").strip()
                if code:
                    selected_codes.add(code)
                if len(selected) >= limit:
                    return selected
        if selected:
            return selected[:limit]
        fallback: List[Dict[str, Any]] = []
        for candidate in candidates or []:
            if not isinstance(candidate, dict) or cls._stock_value(candidate) <= 0:
                continue
            normalized = dict(candidate)
            normalized["recommendation_category"] = "available_inventory"
            normalized["recommendation_category_label"] = cls._available_inventory_label(language)
            normalized["category"] = normalized.get("category") or normalized["recommendation_category_label"]
            normalized["match_keywords"] = []
            normalized["recommendation_reason"] = cls._outdoor_recommendation_reason(
                query,
                normalized,
                category_label=normalized["recommendation_category_label"],
                matched_keywords=[],
                language=language,
            )
            normalized["reason"] = normalized["recommendation_reason"]
            normalized.setdefault("source", "CERP")
            normalized.setdefault("source_trace", cls._source_trace(normalized))
            fallback.append(normalized)
            if len(fallback) >= min(limit, 10):
                break
        return fallback

    @staticmethod
    def _available_inventory_label(language: str) -> str:
        if str(language or "").lower().startswith("ja"):
            return "\u5728\u5eab\u3042\u308a\u5546\u54c1"
        if str(language or "").lower().startswith(("zh", "tw")):
            return "\u6709\u5eab\u5b58\u5546\u54c1"
        return "Available inventory"

    @staticmethod
    def _outdoor_recommendation_reason(
        query: str,
        product: Dict[str, Any],
        *,
        category_label: str,
        matched_keywords: List[str],
        language: str,
    ) -> str:
        stock = CerpRecommendationService._stock_value(product)
        if str(language or "").lower().startswith("ja"):
            parts = [f"{category_label}\u306e\u7528\u9014\u306b\u5408\u3046\u5546\u54c1\u3067\u3059"]
            if stock > 0:
                parts.append(f"\u73fe\u5728\u5728\u5eab {stock}")
            parts.append("\u767b\u5c71\u30fb\u30ad\u30e3\u30f3\u30d7\u30fb\u91e3\u308a\u306e\u6e96\u5099\u54c1\u3068\u3057\u3066\u6271\u3044\u3084\u3059\u3044\u9078\u629e\u80a2\u3067\u3059")
            return "\u3001".join(parts) + "\u3002"
        if str(language or "").lower().startswith(("zh", "tw")):
            parts = [f"\u7b26\u5408{category_label}\u9700\u6c42"]
            if stock > 0:
                parts.append(f"\u76ee\u524d\u6709\u5eab\u5b58 {stock}")
            parts.append("\u9069\u5408\u4f5c\u70ba\u767b\u5c71\u3001\u9732\u71df\u6216\u91e3\u9b5a\u884c\u7a0b\u7684\u6e96\u5099\u54c1")
            return "\uff0c".join(parts) + "\u3002"
        parts = [f"Fits the {category_label} need"]
        if stock > 0:
            parts.append(f"current stock {stock}")
        parts.append("suitable as practical gear for hiking, camping, or fishing preparation")
        return "; ".join(parts) + "."

    @classmethod
    async def _apply_llm_recommendation_groups(
        cls,
        query: str,
        products: List[Dict[str, Any]],
        *,
        language: str,
        rag_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        fallback_groups = cls._build_fallback_recommendation_groups(products, language=language)
        cls._apply_recommendation_groups_to_products(products, fallback_groups)
        if not products:
            return []
        try:
            raw = await chat_complete(
                cls._recommendation_group_system_prompt(language),
                cls._recommendation_group_user_prompt(
                    query,
                    products,
                    language=language,
                    rag_context=rag_context,
                ),
                temperature=0.2,
            )
            payload = cls._parse_recommendation_group_payload(raw)
            groups = cls._normalize_recommendation_groups(payload, products, fallback_groups, language=language)
            cls._apply_recommendation_groups_to_products(products, groups)
            return groups
        except OpenAIChatHTTPError as exc:
            logger.info(
                "Recommendation group LLM unavailable for %s: HTTP %s",
                exc.model,
                exc.status,
            )
        except Exception as exc:
            logger.info("Recommendation group LLM fallback applied: %s", exc)
        return fallback_groups

    @staticmethod
    def _recommendation_group_system_prompt(language: str) -> str:
        if str(language or "").lower().startswith("ja"):
            answer_language = "natural business Japanese"
        elif str(language or "").lower().startswith(("zh", "tw")):
            answer_language = "Traditional Chinese"
        else:
            answer_language = "English"
        return (
            "You write concise outdoor retail recommendation rationale. "
            f"Answer only in {answer_language}. "
            "Use only the supplied category ids and product codes. "
            "Do not invent products, stock, prices, discounts, brands, or specifications. "
            "Return strict JSON only."
        )

    @classmethod
    def _recommendation_group_user_prompt(
        cls,
        query: str,
        products: List[Dict[str, Any]],
        *,
        language: str,
        rag_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        groups: Dict[str, Dict[str, Any]] = {}
        for product in products or []:
            category_id = str(product.get("recommendation_category") or "available_inventory").strip()
            category_label = str(
                product.get("recommendation_category_label")
                or product.get("category")
                or category_id
            ).strip()
            group = groups.setdefault(
                category_id,
                {
                    "category_id": category_id,
                    "category_label": category_label,
                    "products": [],
                },
            )
            group["products"].append(
                {
                    "code": str(product.get("no") or product.get("code") or product.get("id") or "").strip(),
                    "name": cls._display_name(product),
                    "brand": str(product.get("brand") or product.get("producer") or product.get("supplier") or "").strip(),
                    "spec": str(product.get("spec") or product.get("spec1") or product.get("model") or product.get("vintage") or "").strip(),
                    "stock": cls._stock_value(product),
                    "list_price": product.get("list_price") or product.get("price"),
                    "vip_price": product.get("vip_price"),
                }
            )
        payload = {
            "user_query": query,
            "language": language,
            "rag_context": {
                "available": bool((rag_context or {}).get("hit_count")),
                "notes": (rag_context or {}).get("sections") or [],
            },
            "categories": list(groups.values()),
            "required_json_shape": {
                "groups": [
                    {
                        "category_id": "same as supplied",
                        "category_label": "same as supplied or localized",
                        "need_reason": "one short sentence explaining why this category is needed",
                        "usage": "one short sentence explaining how to use it in this trip/use case",
                        "highlighted_product_codes": ["choose at most one supplied product code for this category"],
                    }
                ]
            },
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _parse_recommendation_group_payload(raw: Any) -> Dict[str, Any]:
        text = str(raw or "").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        return json.loads(text)

    @classmethod
    def _build_fallback_recommendation_groups(
        cls,
        products: List[Dict[str, Any]],
        *,
        language: str,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for product in products or []:
            category_id = str(product.get("recommendation_category") or "available_inventory").strip()
            category_label = str(
                product.get("recommendation_category_label")
                or product.get("category")
                or category_id
            ).strip()
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            group = grouped.setdefault(
                category_id,
                {
                    "category_id": category_id,
                    "category_label": category_label,
                    "need_reason": cls._fallback_group_need_reason(category_label, language),
                    "usage": cls._fallback_group_usage(category_label, language),
                    "highlighted_product_codes": [],
                    "product_codes": [],
                    "llm_generated": False,
                },
            )
            if code:
                group["product_codes"].append(code)
        for group in grouped.values():
            if group["product_codes"] and not group["highlighted_product_codes"]:
                group["highlighted_product_codes"] = [group["product_codes"][0]]
        return list(grouped.values())

    @staticmethod
    def _fallback_group_need_reason(category_label: str, language: str) -> str:
        if str(language or "").lower().startswith("ja"):
            return f"{category_label}は行程中の基本装備を整えるために必要です。"
        if str(language or "").lower().startswith(("zh", "tw")):
            return f"{category_label}是這類行程的基礎準備項目。"
        return f"{category_label} covers a core need for this trip."

    @staticmethod
    def _fallback_group_usage(category_label: str, language: str) -> str:
        if str(language or "").lower().startswith("ja"):
            return "現地で使いやすく、出発前の装備確認にも組み込みやすい項目です。"
        if str(language or "").lower().startswith(("zh", "tw")):
            return "可放入出發前檢查清單，依實際路線與天候調整數量。"
        return "Use it in the pre-trip checklist and adjust quantity for route and weather."

    @classmethod
    def _normalize_recommendation_groups(
        cls,
        payload: Dict[str, Any],
        products: List[Dict[str, Any]],
        fallback_groups: List[Dict[str, Any]],
        *,
        language: str,
    ) -> List[Dict[str, Any]]:
        fallback_by_id = {
            str(group.get("category_id") or ""): dict(group)
            for group in fallback_groups
            if str(group.get("category_id") or "")
        }
        allowed_by_group: Dict[str, set[str]] = {}
        for product in products or []:
            category_id = str(product.get("recommendation_category") or "available_inventory").strip()
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            if category_id and code:
                allowed_by_group.setdefault(category_id, set()).add(code)
        raw_groups = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(raw_groups, list):
            return fallback_groups
        normalized: List[Dict[str, Any]] = []
        used_ids: set[str] = set()
        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue
            category_id = str(raw_group.get("category_id") or "").strip()
            if not category_id or category_id not in fallback_by_id or category_id in used_ids:
                continue
            fallback = fallback_by_id[category_id]
            allowed_codes = allowed_by_group.get(category_id, set())
            highlighted = [
                str(code).strip()
                for code in (raw_group.get("highlighted_product_codes") or [])
                if str(code).strip() in allowed_codes
            ][:1]
            if not highlighted:
                highlighted = list(fallback.get("highlighted_product_codes") or [])[:1]
            need_reason = str(raw_group.get("need_reason") or "").strip()
            usage = str(raw_group.get("usage") or "").strip()
            normalized.append(
                {
                    **fallback,
                    "category_label": str(raw_group.get("category_label") or fallback.get("category_label") or category_id).strip(),
                    "need_reason": need_reason or str(fallback.get("need_reason") or cls._fallback_group_need_reason(category_id, language)),
                    "usage": usage or str(fallback.get("usage") or cls._fallback_group_usage(category_id, language)),
                    "highlighted_product_codes": highlighted,
                    "llm_generated": bool(need_reason or usage),
                }
            )
            used_ids.add(category_id)
        for fallback in fallback_groups:
            category_id = str(fallback.get("category_id") or "").strip()
            if category_id and category_id not in used_ids:
                normalized.append(fallback)
        return normalized

    @staticmethod
    def _apply_recommendation_groups_to_products(
        products: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
    ) -> None:
        group_by_id = {
            str(group.get("category_id") or ""): group
            for group in groups or []
            if str(group.get("category_id") or "")
        }
        for product in products or []:
            category_id = str(product.get("recommendation_category") or "available_inventory").strip()
            group = group_by_id.get(category_id) or {}
            highlighted = {str(code).strip() for code in (group.get("highlighted_product_codes") or [])}
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            reason = str(group.get("need_reason") or product.get("recommendation_reason") or product.get("reason") or "").strip()
            usage = str(group.get("usage") or "").strip()
            product["recommendation_group_reason"] = reason
            product["recommendation_usage"] = usage
            product["special_recommended"] = bool(code and code in highlighted)
            if reason and usage:
                product["recommendation_reason"] = f"{reason} {usage}"
            elif reason:
                product["recommendation_reason"] = reason
            product["reason"] = product.get("recommendation_reason") or product.get("reason") or ""

    @classmethod
    def _outdoor_no_product_answer(cls, query: str, language: str) -> str:
        categories = cls._outdoor_categories_for_query(query)
        labels = [
            labels.get(language) or labels.get("zh-Hant") or labels.get("en") or category_id
            for category_id, labels, _keywords in categories[:6]
        ]
        if str(language or "").lower().startswith("ja"):
            lines = [
                "\u73fe\u5728\u306e\u5546\u54c1\u5728\u5eab\u3067\u306f\u3001\u3053\u306e\u6761\u4ef6\u306b\u5408\u3046\u63a8\u5968\u5546\u54c1\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093\u3002",
                "\u4e00\u822c\u7684\u306a\u88c5\u5099\u5206\u985e\u3068\u3057\u3066\u306f\u3001\u6b21\u306e\u9805\u76ee\u3092\u78ba\u8a8d\u3057\u3066\u304f\u3060\u3055\u3044\uff1a",
            ]
            lines.extend(f"- {label}" for label in labels)
            return "\n".join(lines)
        if str(language or "").lower().startswith(("zh", "tw")):
            lines = [
                "\u76ee\u524d\u5546\u54c1\u5eab\u5b58\u4e2d\u627e\u4e0d\u5230\u7b26\u5408\u9019\u500b\u63a8\u85a6\u9700\u6c42\u7684\u5546\u54c1\u3002",
                "\u4e00\u822c\u88dd\u5099\u6e96\u5099\u4e0a\uff0c\u5efa\u8b70\u5148\u6aa2\u67e5\u9019\u4e9b\u5206\u985e\uff1a",
            ]
            lines.extend(f"- {label}" for label in labels)
            return "\n".join(lines)
        lines = [
            "No matching Product Inventory items were found for this recommendation request.",
            "As a general preparation checklist, review these categories first:",
        ]
        lines.extend(f"- {label}" for label in labels)
        return "\n".join(lines)

    @staticmethod
    def _resolve_result_limit(
        criteria: Dict[str, Any],
        quote_request: Dict[str, Any],
        query_mode: str,
    ) -> Optional[int]:
        if query_mode in {"exact_inventory_fact_check", "unbounded_inventory_listing"}:
            return None
        for value in (criteria.get("result_limit"), quote_request.get("result_limit")):
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                return max(1, min(number, 20))
        return 5

    @staticmethod
    def _candidate_limit_for_mode(result_limit: Optional[int], query_mode: str) -> int:
        if query_mode in {"exact_inventory_fact_check", "unbounded_inventory_listing"}:
            return _ALL_MATCHING_CANDIDATE_LIMIT
        return max(int(result_limit or 5) * 4, 24)

    @staticmethod
    def _cleanup_criteria(query: str, criteria: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(criteria or {})
        text = str(query or "")
        lowered = text.casefold()
        broad_recommendation = bool(
            re.search(r"\b(?:recommend|list|find|show|which|what)\b", text, flags=re.IGNORECASE)
            and (
                cleaned.get("region")
                or cleaned.get("region_filter")
                or cleaned.get("style")
                or _WINE_STYLE_RE.search(text)
            )
            and (
                _CERP_RECOMMENDATION_RE.search(text)
                or _STOCK_RE.search(text)
                or _COMMERCIAL_FILTER_RE.search(text)
            )
        )
        if not broad_recommendation and _BUILD_CASE_RE.search(text):
            broad_recommendation = bool(
                cleaned.get("region")
                or cleaned.get("region_filter")
                or cleaned.get("style")
                or _WINE_STYLE_RE.search(text)
            )

        excluded_over = re.search(
            r"(?:exclude|excluding|not|without|不要|排除)[^。.!?;；]{0,80}?(?:over|above|more\s+than|超過|高於|大於)\s*(?:nt\$?\s*)?\$?\s*([0-9][0-9,]*(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if excluded_over:
            try:
                cleaned["price_max"] = float(excluded_over.group(1).replace(",", ""))
                cleaned["price_min"] = None
            except (TypeError, ValueError):
                pass
        stock_min = _STOCK_MIN_QUERY_RE.search(text)
        if stock_min:
            try:
                cleaned["stock_min"] = int(stock_min.group(1))
                cleaned["stock_policy"] = "in_stock_only"
            except (TypeError, ValueError):
                pass
        if CerpRecommendationService._query_mode(text) == "unbounded_inventory_listing":
            cleaned["result_limit"] = None
            cleaned["all_matching"] = True

        producer = str(cleaned.get("producer") or "").strip()
        if producer:
            producer = re.sub(r"^(?:find|show|list|which|what|build|assemble|create)\s+", "", producer, flags=re.IGNORECASE).strip(" '\"")
            region = str(cleaned.get("region") or cleaned.get("region_filter") or "").strip()
            if (
                not producer
                or producer.casefold() in {"all", "list all", "find all", "show all"}
                or (broad_recommendation and len(producer) <= 2)
                or (region and producer.casefold() == region.casefold())
                or (
                    broad_recommendation
                    and (
                        re.search(r"\b(?:recommend|list|find|show|which|what|build|assemble|create)\b", producer, flags=re.IGNORECASE)
                        or (region and region.casefold() in producer.casefold())
                    )
                )
            ):
                producer = ""
            cleaned["producer"] = producer or None

        wine_name = str(cleaned.get("wine_name") or "").strip()
        if wine_name:
            if "exclude" in lowered or "excluding" in lowered:
                wine_name = ""
            elif broad_recommendation and re.search(
                r"\b(?:wines?|bottles?|currently|available|cerp|with|vip|price|under|below|stock|inventory)\b",
                wine_name,
                flags=re.IGNORECASE,
            ):
                wine_name = ""
            elif "puligny" in lowered and len(wine_name) > 40:
                wine_name = "Puligny"
            cleaned["wine_name"] = wine_name or None

        variants = list(cleaned.get("query_variants") or [])
        for candidate in (
            cleaned.get("keywords"),
            cleaned.get("region"),
            cleaned.get("region_filter"),
            cleaned.get("wine_name"),
            cleaned.get("producer"),
        ):
            candidate_text = str(candidate or "").strip()
            if candidate_text and candidate_text not in variants:
                variants.append(candidate_text)
        if cleaned.get("region") and cleaned.get("color"):
            variant = f"{cleaned['region']} {cleaned['color']} wine"
            if variant not in variants:
                variants.append(variant)
        cleaned["query_variants"] = variants
        return cleaned

    @staticmethod
    def _normalize_tokens(value: Any) -> List[str]:
        return [
            token.casefold()
            for token in _TEXT_TOKEN_RE.findall(str(value or ""))
            if token and token.casefold() not in _EXACT_FACT_STOPWORDS
        ]

    @classmethod
    def _apply_exact_fact_terms(cls, query: str, criteria: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(criteria or {})
        subject = _FACT_CLAUSE_RE.sub("", str(query or ""))
        subject = re.sub(
            r"\b(?:do\s+we|are\s+we|currently|current|carry|carried|sell|have|stock|inventory|available|availability|in\s+cerp|on\s+cerp)\b",
            " ",
            subject,
            flags=re.IGNORECASE,
        )
        vintage_match = re.search(r"\b((?:19|20)\d{2})\b", subject)
        if vintage_match:
            cleaned["vintage"] = cleaned.get("vintage") or vintage_match.group(1)
            subject = subject.replace(vintage_match.group(1), " ")
        tokens = cls._normalize_tokens(subject)
        cleaned["_exact_fact_terms"] = tokens
        cleaned["result_limit"] = None
        cleaned["all_matching"] = False
        return cleaned

    @staticmethod
    def _stock_value(product: Dict[str, Any]) -> int:
        for key in ("stock_qty", "stock", "total_stock"):
            try:
                value = int(float(product.get(key) or 0))
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                return value
        return 0

    @classmethod
    def _select_products(
        cls,
        candidates: List[Dict[str, Any]],
        criteria: Dict[str, Any],
        result_limit: Optional[int],
        *,
        query: str = "",
        query_mode: str = "bounded_recommendation",
        allow_alternatives: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        exact: List[Dict[str, Any]] = []
        alternatives: List[Tuple[float, int, Dict[str, Any]]] = []
        require_stock = str(criteria.get("stock_policy") or "") == "in_stock_only"
        require_wine_product = cls._requires_wine_product(query, criteria)
        stock_min = cls._criteria_stock_min(criteria)
        for item in candidates or []:
            if not isinstance(item, dict):
                continue
            stock = cls._stock_value(item)
            if require_stock and stock <= 0:
                continue
            if stock_min is not None and stock < stock_min:
                continue
            normalized = dict(item)
            normalized.setdefault("source", "CERP")
            normalized.setdefault("source_trace", cls._source_trace(normalized))
            if require_wine_product and not cls._is_wine_product(normalized):
                continue
            if cls._violates_hard_price_filter(normalized, criteria):
                continue
            exact_match = (
                cls._exact_fact_product_matches(normalized, criteria)
                if query_mode == "exact_inventory_fact_check"
                else quote_product_matches_criteria(normalized, criteria)
            )
            if exact_match:
                normalized["match_type"] = "exact"
                exact.append(normalized)
                continue
            if not allow_alternatives:
                continue
            score = quote_product_alternative_score(normalized, criteria)
            if score > 0:
                normalized["match_type"] = "alternative"
                alternatives.append((score, stock, normalized))
        alternatives.sort(key=lambda item: (item[0], item[1]), reverse=True)
        if result_limit is None:
            selected = exact
            if allow_alternatives:
                selected = selected + [item[2] for item in alternatives]
            return selected, exact, [item[2] for item in alternatives]
        selected = exact[:result_limit]
        if allow_alternatives and len(selected) < result_limit:
            selected.extend(item[2] for item in alternatives[: result_limit - len(selected)])
        return selected, exact[:result_limit], [item[2] for item in alternatives[:result_limit]]

    @staticmethod
    def _criteria_stock_min(criteria: Dict[str, Any]) -> Optional[int]:
        try:
            value = criteria.get("stock_min")
            if value is None:
                return None
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @classmethod
    def _exact_fact_product_matches(cls, product: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
        vintage = str(criteria.get("vintage") or "").strip()
        product_vintage = str(product.get("vintage") or "").strip()
        if vintage and product_vintage and vintage != product_vintage:
            return False
        if vintage and not product_vintage:
            return False
        code = str(criteria.get("sku") or criteria.get("code") or "").strip()
        if code:
            product_code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            return product_code.casefold() == code.casefold()
        terms = [token for token in criteria.get("_exact_fact_terms") or [] if token]
        if not terms:
            return quote_product_matches_criteria(product, criteria)
        haystack = " ".join(
            str(product.get(key) or "")
            for key in ("producer", "name", "name_en", "name_ch", "product", "no", "code", "id")
        ).casefold()
        return all(term in haystack for term in terms)

    @staticmethod
    def _requires_wine_product(query: str, criteria: Dict[str, Any]) -> bool:
        text = " ".join(
            str(value or "")
            for value in (
                query,
                criteria.get("keywords"),
                criteria.get("region"),
                criteria.get("region_filter"),
                criteria.get("wine_name"),
            )
        )
        return bool(_WINE_PRODUCT_REQUEST_RE.search(text))

    @staticmethod
    def _is_wine_product(product: Dict[str, Any]) -> bool:
        text = " ".join(
            str(product.get(key) or "")
            for key in (
                "no",
                "code",
                "id",
                "name",
                "name_en",
                "name_ch",
                "producer",
                "region",
                "wine_type",
                "color",
                "rating",
                "category",
                "type",
            )
        )
        if _NON_WINE_PRODUCT_RE.search(text):
            return False
        if product.get("vintage") not in (None, ""):
            return True
        if product.get("capacity_ml") or product.get("capacity"):
            return True
        return bool(
            re.search(
                r"(?:champagne|burgundy|bourgogne|chablis|puligny|meursault|vosne|sparkling|red|white|rose|rosé|wine|香檳|勃根地|紅酒|白酒|氣泡)",
                text,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def _price_value(product: Dict[str, Any], scope: Any) -> Optional[float]:
        fields = ("vip_price", "vip", "display_quote_price") if str(scope or "").strip().lower() == "vip" else (
            "list_price",
            "price",
            "display_quote_price",
            "vip_price",
        )
        for field in fields:
            try:
                value = product.get(field)
                if value in (None, ""):
                    continue
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    @classmethod
    def _violates_hard_price_filter(cls, product: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
        price_min = criteria.get("price_min")
        price_max = criteria.get("price_max")
        if price_min is None and price_max is None:
            return False
        price = cls._price_value(product, criteria.get("price_scope"))
        if price is None:
            return True
        try:
            if price_min is not None and price < float(price_min):
                return True
            if price_max is not None and price > float(price_max):
                return True
        except (TypeError, ValueError):
            return True
        return False

    @staticmethod
    def _source_trace(product: Dict[str, Any]) -> str:
        code = str(product.get("no") or product.get("code") or product.get("id") or "-").strip()
        timestamp = str(product.get("timestamp") or datetime.now(timezone.utc).isoformat())
        return f"CERP ExportProduct/ExportProductsInfo | sku:{code} | timestamp:{timestamp}"

    @classmethod
    def _build_cerp_results(
        cls,
        products: List[Dict[str, Any]],
        *,
        generated_at: str,
        total_match_count: Optional[int] = None,
        displayed_count: Optional[int] = None,
        result_truncated: bool = False,
        query_mode: str = "bounded_recommendation",
    ) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        for product in products or []:
            code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
            source_trace = str(product.get("source_trace") or cls._source_trace(product))
            timestamp = str(product.get("timestamp") or generated_at)
            proof = {
                "type": "cerp",
                "code": code,
                "stock": product.get("stock") or product.get("stock_qty") or product.get("total_stock"),
                "price": product.get("price") or product.get("list_price"),
                "vip_price": product.get("vip_price"),
                "timestamp": timestamp,
                "endpoint": "CERP ExportProduct/ExportProductsInfo",
            }
            items.append(
                {
                    "code": code,
                    "no": code,
                    "name": product.get("name") or product.get("name_en") or product.get("name_ch") or "",
                    "producer": product.get("producer") or "",
                    "vintage": product.get("vintage"),
                    "category": product.get("recommendation_category_label") or product.get("category") or "",
                    "recommendation_category": product.get("recommendation_category") or "",
                    "recommendation_group_reason": product.get("recommendation_group_reason") or "",
                    "recommendation_usage": product.get("recommendation_usage") or "",
                    "recommendation_reason": product.get("recommendation_reason") or product.get("reason") or "",
                    "reason": product.get("reason") or product.get("recommendation_reason") or "",
                    "special_recommended": bool(product.get("special_recommended")),
                    "match_keywords": product.get("match_keywords") or [],
                    "stock": proof["stock"],
                    "price": proof["price"],
                    "list_price": product.get("list_price") or proof["price"],
                    "vip_price": proof["vip_price"],
                    "status": product.get("status") or product.get("availability"),
                    "source": "CERP",
                    "source_trace": source_trace,
                    "timestamp": timestamp,
                    "endpoint": "CERP ExportProduct/ExportProductsInfo",
                    "proof": proof,
                }
            )
        return {
            "kind": "cerp_recommendation",
            "count": len(items),
            "proof_count": len(items),
            "source": "CERP",
            "generated_at": generated_at,
            "query_mode": query_mode,
            "total_match_count": total_match_count if total_match_count is not None else len(items),
            "displayed_count": displayed_count if displayed_count is not None else len(items),
            "result_truncated": result_truncated,
            "limit_reason": "answer_text_display_limit" if result_truncated else "",
            "items": items,
        }

    @staticmethod
    def _build_citations(cerp_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        citations: List[Dict[str, Any]] = []
        for item in cerp_results.get("items") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("no") or "").strip()
            source_trace = str(item.get("source_trace") or "").strip()
            title = " ".join(
                part
                for part in [
                    "CERP",
                    str(item.get("producer") or "").strip(),
                    str(item.get("name") or "").strip(),
                ]
                if part
            ).strip()
            citations.append(
                {
                    "id": f"cerp:{code or source_trace}",
                    "source_type": "cerp_snapshot",
                    "title": title,
                    "text": " | ".join(
                        part
                        for part in [
                            code,
                            str(item.get("producer") or "").strip(),
                            str(item.get("name") or "").strip(),
                            f"stock {item.get('stock')}" if item.get("stock") is not None else "",
                            f"list price {item.get('list_price')}" if item.get("list_price") is not None else "",
                            f"VIP price {item.get('vip_price')}" if item.get("vip_price") is not None else "",
                            source_trace,
                        ]
                        if part
                    ),
                    "meta": {
                        "source_family": "cerp_snapshot",
                        "source_name": "CERP",
                        "source_trace": source_trace,
                        "code": code,
                        "producer": item.get("producer") or "",
                        "name": item.get("name") or "",
                        "vintage": item.get("vintage"),
                        "stock": item.get("stock"),
                        "list_price": item.get("list_price"),
                        "vip_price": item.get("vip_price"),
                        "timestamp": item.get("timestamp"),
                        "endpoint": item.get("endpoint") or "CERP ExportProduct/ExportProductsInfo",
                    },
                }
            )
        return citations

    @staticmethod
    def _build_absence_citation(query: str, criteria: Dict[str, Any], generated_at: str) -> Dict[str, Any]:
        return {
            "id": f"cerp-query:{generated_at}",
            "source_type": "cerp_snapshot",
            "title": "CERP exact inventory check",
            "text": f"CERP exact inventory check for {query} returned no exact product rows at {generated_at}.",
            "meta": {
                "source_family": "cerp_snapshot",
                "source_name": "CERP",
                "source_trace": f"CERP ExportProduct/ExportProductsInfo | exact query:{query} | timestamp:{generated_at}",
                "timestamp": generated_at,
                "endpoint": "CERP ExportProduct/ExportProductsInfo",
                "verified_absence": True,
                "criteria": criteria,
            },
        }

    @staticmethod
    def _build_answer_text(
        *,
        query: str,
        products: List[Dict[str, Any]],
        criteria: Dict[str, Any],
        language: str,
        query_mode: str = "bounded_recommendation",
        total_count: int = 0,
        displayed_count: int = 0,
        result_truncated: bool = False,
    ) -> str:
        if query_mode == "generic_inventory_listing":
            if not products:
                return t("cerp.generic_listing_empty", language)
            count = total_count or len(products)
            lines = [t("cerp.generic_listing_header", language, count=count)]
            spec_label = t("cerp.labels.spec", language)
            stock_label = t("cerp.labels.stock", language)
            price_label = t("cerp.labels.price", language)
            for index, product in enumerate(products, start=1):
                code = str(product.get("no") or product.get("code") or product.get("id") or "-").strip()
                name = str(product.get("name") or product.get("name_ch") or product.get("name_en") or "-").strip()
                spec = str(product.get("spec") or product.get("model") or product.get("vintage") or "").strip()
                stock = product.get("stock") or product.get("stock_qty") or product.get("total_stock") or 0
                price = product.get("list_price") or product.get("price")
                bits = [code, name]
                if spec:
                    bits.append(f"{spec_label} {spec}")
                bits.append(f"{stock_label} {stock}")
                if price is not None:
                    bits.append(f"{price_label} {price}")
                lines.append(f"{index}. " + " / ".join(bits))
            return "\n".join(lines)

        if query_mode == "outdoor_product_recommendation":
            if not products:
                return CerpRecommendationService._outdoor_no_product_answer(query, language)
            if str(language or "").lower().startswith("ja"):
                lines = [f"\u5546\u54c1\u5728\u5eab\u304b\u3089 {len(products)} \u4ef6\u306e\u63a8\u5968\u5546\u54c1\u3092\u9078\u3073\u307e\u3057\u305f\uff1a"]
                product_list_label = "\u5546\u54c1\u30ea\u30b9\u30c8"
                special_label = "\u7279\u306b\u63a8\u5968"
                stock_label = "\u5728\u5eab"
                list_price_label = "\u6a19\u6e96\u4fa1\u683c"
                vip_price_label = "VIP \u4fa1\u683c"
            elif str(language or "").lower().startswith(("zh", "tw")):
                lines = [f"\u6211\u5f9e\u5546\u54c1\u5eab\u5b58\u4e2d\u9078\u51fa {len(products)} \u7b46\u63a8\u85a6\u5546\u54c1\uff1a"]
                product_list_label = "\u7522\u54c1\u5217\u8868"
                special_label = "\u7279\u5225\u63a8\u85a6"
                stock_label = "\u5eab\u5b58"
                list_price_label = "\u6a19\u6e96\u50f9"
                vip_price_label = "VIP \u50f9"
            else:
                lines = [f"I found {len(products)} recommended Product Inventory item(s):"]
                product_list_label = "Product list"
                special_label = "Special pick"
                stock_label = "Stock"
                list_price_label = "List price"
                vip_price_label = "VIP price"
            grouped: Dict[str, Dict[str, Any]] = {}
            for product in products:
                category_id = str(product.get("recommendation_category") or "available_inventory").strip()
                category = str(product.get("recommendation_category_label") or product.get("category") or category_id).strip()
                group = grouped.setdefault(
                    category_id,
                    {
                        "category": category,
                        "reason": str(product.get("recommendation_group_reason") or product.get("recommendation_reason") or product.get("reason") or "").strip(),
                        "usage": str(product.get("recommendation_usage") or "").strip(),
                        "products": [],
                    },
                )
                if not group.get("usage") and product.get("recommendation_usage"):
                    group["usage"] = str(product.get("recommendation_usage") or "").strip()
                group["products"].append(product)
            for group in grouped.values():
                category = str(group.get("category") or "").strip()
                reason = str(group.get("reason") or "").strip()
                usage = str(group.get("usage") or "").strip()
                summary = " ".join(part for part in [reason, usage] if part).strip()
                lines.append("")
                lines.append(f"{category}: {summary}" if summary else f"{category}:")
                lines.append(f"{product_list_label}:")
                for product in group.get("products") or []:
                    display_name = CerpRecommendationService._display_name(product)
                    code = str(product.get("no") or product.get("code") or product.get("id") or "-").strip()
                    stock = product.get("stock") or product.get("stock_qty") or product.get("total_stock") or 0
                    vip_price = product.get("vip_price")
                    list_price = product.get("list_price") or product.get("price")
                    marker = f"\u2605 {special_label}: " if product.get("special_recommended") else "- "
                    lines.append(
                        f"{marker}{code} / {display_name} / {stock_label}: {stock} / "
                        f"{list_price_label}: {list_price if list_price is not None else '-'} / "
                        f"{vip_price_label}: {vip_price if vip_price is not None else '-'}"
                    )
            return "\n".join(lines)

        if not products:
            if query_mode == "exact_inventory_fact_check":
                if str(language or "").lower().startswith(("zh", "tw")):
                    return (
                        f"沒有。CERP 目前沒有找到與「{query}」完全一致的在售品項；"
                        "我沒有列出相近或替代酒款。"
                    )
                return (
                    f"No. CERP currently has no exact sellable item matching \"{query}\". "
                    "I did not list nearby or alternative wines."
                )
            return t("cerp.recommendation.no_results", language, query=query)
        lines = [t("cerp.recommendation.title", language, count=total_count or len(products), query=query)]
        if result_truncated:
            if str(language or "").lower().startswith(("zh", "tw")):
                lines.append(f"共 {total_count} 筆符合條件；下方文字先列前 {displayed_count} 筆，完整結果保留在 CERP table / metadata。")
            else:
                lines.append(f"{total_count} item(s) matched; this answer lists the first {displayed_count}, with the full result set kept in the CERP table / metadata.")
        if query_mode == "exact_inventory_fact_check":
            if str(language or "").lower().startswith(("zh", "tw")):
                lines.append("有。CERP 找到以下完全一致品項：")
            else:
                lines.append("Yes. CERP found the following exact item(s):")
        for index, product in enumerate(products, start=1):
            name = product.get("name") or product.get("name_en") or product.get("name_ch") or product.get("no") or ""
            producer = product.get("producer") or ""
            stock = product.get("stock") or product.get("stock_qty") or product.get("total_stock") or 0
            vip_price = product.get("vip_price")
            list_price = product.get("list_price") or product.get("price")
            vintage = product.get("vintage") or ""
            source_trace = product.get("source_trace") or CerpRecommendationService._source_trace(product)
            rationale = CerpRecommendationService._pairing_rationale(query, product, language=language)
            confidence = CerpRecommendationService._confidence_label(product, language=language)
            display_name = CerpRecommendationService._display_name(product)
            if str(language or "").lower().startswith(("zh", "tw")):
                lines.extend(
                    [
                        f"{index}. {display_name}",
                        f"   - 為什麼適合：{rationale}",
                        f"   - 庫存：{stock}；標準售價：{list_price if list_price is not None else '-'}；VIP 價格：{vip_price if vip_price is not None else '-'}。",
                        f"   - CERP 引用：{source_trace}",
                        f"   - 信心：{confidence}",
                    ]
                )
            else:
                lines.extend(
                    [
                        f"{index}. {display_name}",
                        f"   - Why it fits: {rationale}",
                        f"   - Current stock: {stock}; list price: {list_price if list_price is not None else '-'}; VIP price: {vip_price if vip_price is not None else '-'}.",
                        f"   - CERP citation: {source_trace}",
                        f"   - Confidence: {confidence}",
                    ]
                )
        return "\n".join(lines)

    @staticmethod
    def _display_name(product: Dict[str, Any]) -> str:
        producer = str(product.get("producer") or "").strip()
        name = str(product.get("name") or product.get("name_en") or product.get("name_ch") or product.get("no") or "").strip()
        vintage_raw = product.get("vintage")
        vintage = ""
        if vintage_raw not in (None, ""):
            try:
                vintage_number = float(vintage_raw)
                vintage = str(int(vintage_number)) if vintage_number.is_integer() else str(vintage_raw)
            except (TypeError, ValueError):
                vintage = str(vintage_raw).strip()
        parts: List[str] = []
        if producer and not name.casefold().startswith(producer.casefold()):
            parts.append(producer)
        if name:
            parts.append(name)
        if vintage and vintage.casefold() not in " ".join(parts).casefold():
            parts.append(vintage)
        return " ".join(part for part in parts if part).strip()

    @staticmethod
    def _pairing_rationale(query: str, product: Dict[str, Any], *, language: str) -> str:
        text = " ".join(
            str(value or "")
            for value in (
                query,
                product.get("name"),
                product.get("name_en"),
                product.get("name_ch"),
                product.get("region"),
                product.get("wine_type"),
                product.get("color"),
                product.get("rating"),
            )
        ).casefold()
        zh = str(language or "").lower().startswith(("zh", "tw"))
        if "duck" in text or "鴨" in text:
            return (
                "紅布根地的酸度、紅果調性與中等單寧能平衡烤鴨油脂，不會壓過肉質。"
                if zh
                else "Red Burgundy's acidity, red-fruit profile, and moderate tannin fit roast duck without overwhelming the meat."
            )
        if "champagne" in text:
            return (
                "香檳的酸度與氣泡能提升清爽度，適合作為開胃或搭配油脂較高的菜式。"
                if zh
                else "Champagne's acidity and mousse add freshness, making it useful for aperitif service or richer dishes."
            )
        if "burgundy" in text or "bourgogne" in text:
            return (
                "此款符合布根地風格方向，酸度與果味通常適合需要細緻結構的餐酒搭配。"
                if zh
                else "It fits the Burgundy direction, where acidity and fruit profile usually support precise food pairing."
            )
        return (
            "此款符合提問中的酒款方向與 CERP 商業條件，可作為目前可售清單的候選。"
            if zh
            else "It matches the requested wine style and CERP commercial filters, so it is a current sellable candidate."
        )

    @staticmethod
    def _confidence_label(product: Dict[str, Any], *, language: str) -> str:
        has_stock = CerpRecommendationService._stock_value(product) > 0
        has_price = any(product.get(key) not in (None, "") for key in ("list_price", "price", "vip_price"))
        has_trace = bool(product.get("source_trace"))
        high = has_stock and has_price and has_trace
        zh = str(language or "").lower().startswith(("zh", "tw"))
        if high:
            return "高：SKU、庫存、價格與 CERP timestamp 都有來源。" if zh else "High: SKU, stock, price, and CERP timestamp are sourced."
        return "中：有 CERP 商品資料，但部分價格或來源欄位不完整。" if zh else "Medium: CERP product data is present, but some price or source fields are incomplete."
