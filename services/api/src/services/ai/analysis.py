import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from ...core import db
from ...pipelines.nlu.intent import detect_intent as _detect_intent
from ...pipelines.rag.query_rewrite import expand_aliases as _expand_aliases
from ...schemas.ai import AnalysisResult, Intent
from .attachment_understanding import AttachmentUnderstandingService
from .url_product_lookup import UrlProductLookupService

try:
    from .behavior_profiles import get_behavior_profile
except Exception:  # pragma: no cover - keeps isolated unit-test loaders simple.
    def get_behavior_profile(prompt_category: Optional[str]) -> Dict[str, Any]:
        category = str(prompt_category or "").strip()
        if category in {"source_validation", "critic_score_lookup", "terroir_comparison", "url_product_lookup"}:
            return {"source_policy": "authoritative_external_required"}
        if category == "quote_recommendation":
            return {"source_policy": "internal_only"}
        return {"source_policy": "internal_preferred"}

logger = logging.getLogger(__name__)


LATEST_INFO_TOKENS = {
    "latest",
    "recent",
    "news",
    "new release",
    "release",
    "past month",
    "最新",
    "最近",
    "近況",
    "近一個月",
    "新聞",
    "消息",
    "動態",
    "發布",
    "發售",
}

SOURCE_TOKENS = {
    "citation",
    "source",
    "sources",
    "reference",
    "references",
    "official",
    "website",
    "web site",
    "official website",
    "official site",
    "官網",
    "官方網站",
    "官方來源",
    "來源",
    "出處",
    "網站",
    "網址",
    "連結",
}

CRITIC_TOKENS = {
    "score",
    "scores",
    "points",
    "rating",
    "ratings",
    "critic",
    "評分",
    "分數",
    "酒評",
    "vinous",
    "decanter",
    "burghound",
    "jasper",
    "wine advocate",
}
PRODUCER_NOISE_TOKENS = {
    "wine advocate",
    "jasper morris",
    "burghound",
    "vinous",
    "decanter",
    "drinking window",
    "review page",
    "score page",
    "mw page",
    "tasted november",
    "tasted ",
    "db:",
    "page",
    "score",
    "clos colin banc",
    "comtes lafon db",
    "colin-deléger",
    "colin-deleger",
}

IMAGE_TOKENS = {"image", "photo", "picture", "圖片", "照片", "相片", "標籤照"}
URL_TOKENS = {"url", "link", "website", "official website", "official site", "網址", "連結", "官網", "官方網站"}
QUOTE_TOKENS = {
    "recommend",
    "recommendation",
    "pairing",
    "quote",
    "quotation",
    "報價",
    "報價單",
    "報價清單",
    "推薦",
    "建議",
    "送禮",
}
INVENTORY_TOKENS = {"inventory", "stock", "availability", "庫存", "現貨", "有貨", "缺貨", "可供貨"}
TASTING_NOTE_TOKENS = {
    "tasting note",
    "tasting notes",
    "note",
    "notes",
    "aroma",
    "aromas",
    "palate",
    "finish",
    "mouthfeel",
    "flavor",
    "flavour",
    "品飲",
    "試飲",
    "品酒",
    "酒評筆記",
    "品飲筆記",
    "香氣",
    "口感",
    "尾韻",
    "風味",
}
PRODUCER_RANKING_TOKENS = {
    "best producers",
    "top producers",
    "great producers",
    "leading producers",
    "producer shortlist",
    "best yss",
    "top yss",
    "best estates",
    "top estates",
    "best wineries",
    "top wineries",
    "\u6700\u4f73\u9152\u838a",
    "\u540d\u5bb6",
    "\u540d\u838a",
    "\u9818\u5148\u9152\u838a",
    "\u503c\u5f97\u95dc\u6ce8\u7684\u9152\u838a",
}
VINEYARD_LOOKUP_TOKENS = {
    "clos vougeot",
    "clos de vougeot",
    "vineyard",
    "vineyards",
    "climat",
    "lieu-dit",
    "lieu dit",
    "grand cru",
    "premier cru",
    "1er cru",
    "葡萄園",
    "一級園",
    "特級園",
}
TERROIR_TOKENS = {
    "difference",
    "differences",
    "compare",
    "comparison",
    "terroir",
    "village",
    "soil",
    "風土",
    "比較",
    "差異",
    "村莊",
    "土壤",
}
BRAND_PROFILE_TOKENS = {
    "detail",
    "details",
    "describe",
    "description",
    "introduce",
    "background",
    "story",
    "history",
    "winery",
    "estate",
    "producer",
    "vineyard",
    "vineyards",
    "region",
    "winemaking",
    "who is",
    "詳細描述",
    "詳細介紹",
    "介紹",
    "描述",
    "酒莊",
    "背景",
    "背景故事",
    "葡萄園",
    "產區",
    "產區資訊",
    "釀造",
    "釀造技巧",
    "歷史",
    "酒莊故事",
    "介紹",
    "背景",
    "歷史",
    "酒莊",
    "生產者",
    "葡萄園",
    "釀造",
    "資料",
}

BRAND_PROFILE_TOKENS_ZH = {
    "\u8a73\u7d30\u63cf\u8ff0",
    "\u8a73\u7d30\u4ecb\u7d39",
    "\u4ecb\u7d39",
    "\u63cf\u8ff0",
    "\u9152\u838a",
    "\u80cc\u666f",
    "\u80cc\u666f\u6545\u4e8b",
    "\u8461\u8404\u5712",
    "\u7522\u5340",
    "\u7522\u5340\u8cc7\u8a0a",
    "\u91c0\u9020",
    "\u91c0\u9020\u6280\u5de7",
    "\u6b77\u53f2",
    "\u9152\u838a\u6545\u4e8b",
}

ALIAS_QUERY_STOP_WORDS = {
    "tell",
    "about",
    "please",
    "describe",
    "what",
    "which",
    "who",
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "there",
    "been",
    "site",
    "url",
    "link",
    "official",
    "source",
    "sources",
    "reference",
    "references",
    "website",
    "web",
    "latest",
    "recent",
    "news",
    "release",
    "new",
    "for",
    "from",
    "with",
    "into",
    "onto",
    "over",
    "under",
    "this",
    "that",
    "these",
    "those",
    "here",
    "their",
    "them",
    "or",
    "and",
    "background",
    "history",
    "vineyard",
    "vineyards",
    "winemaking",
    "score",
    "scores",
    "quote",
    "inventory",
    "price",
    "wine",
    "advocate",
    "jasper",
    "morris",
    "burghound",
    "vinous",
    "decanter",
    "drinking",
    "window",
    "page",
    "ys",
    "estate",
    "winery",
    "producer",
}

ALLOWED_ALIAS_FILTER_KEYS = {"producer", "region", "style", "classification", "grape", "grape_varieties"}
EMPTY_ENTITY_SENTINELS = {"none", "null", "n/a", "na", "unknown", "nil"}

REGION_ALIASES = {
    "Burgundy": ("burgundy", "bourgogne", "\u5e03\u6839\u5730"),
    "Champagne": ("champagne", "\u9999\u6ab3"),
    "Bordeaux": ("bordeaux", "\u6ce2\u723e\u591a"),
    "Alsace": ("alsace", "\u963f\u723e\u85a9\u65af"),
    "Loire": ("loire", "\u7f85\u74e6\u6cb3"),
}
REGION_VINTAGE_OVERVIEW_TOKENS = {
    "vintage",
    "year",
    "characteristic",
    "characteristics",
    "style",
    "\u5e74\u4efd",
    "\u7279\u8272",
    "\u7279\u5fb5",
    "\u98a8\u683c",
    "\u7d05\u767d\u9152",
    "\u7d05\u9152",
    "\u767d\u9152",
}

LATEST_INFO_TOKENS.update({"最新", "近期", "最近", "新聞", "新上市", "新釋出"})
SOURCE_TOKENS.update({"引用", "來源", "資訊來源", "資料來源", "官方", "官網", "官方網站", "網站", "網址"})
SOURCE_TOKENS.update({"文件", "哪份文件", "第幾頁", "頁碼", "第幾行", "行號", "哪個網站", "引用哪個網站"})
CRITIC_TOKENS.update({"酒評", "評分", "分數", "雜誌", "權威酒評", "專業酒評", "酒評家"})
IMAGE_TOKENS.update({"圖片", "照片", "酒標"})
URL_TOKENS.update({"網址", "連結", "網站", "官方網站"})
QUOTE_TOKENS.update({"推薦", "建議", "搭配", "報價", "詢價", "送禮", "熱門"})
INVENTORY_TOKENS.update({"庫存", "現貨", "有貨", "可售", "有賣", "價格", "價錢", "官網"})
OUTDOOR_ADVICE_TOPIC_RE = re.compile(
    r"(?:\u7389\u5c71|\u77f3\u9580\u5c71|[\u4e00-\u9fff]{1,8}\u5c71|\u767b\u5c71|\u5065\u884c|\u9732\u71df|\u91e3\u9b5a|\u91e3\u9ede|\u91e3\u5834|"
    r"\u6d77\u91e3|\u6eaa\u91e3|\u6c34\u5eab\u91e3|\u78ef\u91e3|\u8def\u4e9e|\u8239\u91e3|\u6236\u5916|"
    r"hiking|trekking|mountain|camping|fishing|fishery|outdoor)",
    re.IGNORECASE,
)
OUTDOOR_ADVICE_REQUEST_RE = re.compile(
    r"(?:\u63a8\u85a6|\u5efa\u8b70|\u6e96\u5099|\u5217\u51fa|\u6e05\u55ae|\u88dd\u5099|\u5668\u6750|"
    r"\u5730\u9ede|\u91e3\u9ede|\u91e3\u5834|\u5834\u6240|\u666f\u9ede|\u8def\u7dda|\u884c\u7a0b|\u54ea\u88e1|\u53bb\u54ea|"
    r"recommend|suggest|prepare|bring|pack|packing|checklist|gear|equipment|list|location|spot|place|where)",
    re.IGNORECASE,
)
OUTDOOR_LOCATION_ADVICE_RE = re.compile(
    r"(?:\u91e3\u9b5a|\u91e3\u9ede|\u91e3\u5834|\u6d77\u91e3|\u6eaa\u91e3|\u767b\u5c71|\u5065\u884c|\u9732\u71df|\u6236\u5916|"
    r"[\u4e00-\u9fff]{1,8}\u5c71|fishing|hiking|camping|outdoor).{0,24}"
    r"(?:\u5730\u9ede|\u91e3\u9ede|\u91e3\u5834|\u5834\u6240|\u666f\u9ede|\u8def\u7dda|\u884c\u7a0b|\u63a8\u85a6|\u54ea\u88e1|\u53bb\u54ea|"
    r"location|spot|place|route|where|recommend)"
    r"|(?:\u53f0\u7063|\u53f0\u5317|\u65b0\u5317|\u57fa\u9686|\u6843\u5712|\u65b0\u7af9|\u82d7\u6817|\u53f0\u4e2d|\u5357\u6295|\u5609\u7fa9|\u53f0\u5357|\u9ad8\u96c4|\u5c4f\u6771|\u5b9c\u862d|\u82b1\u84ee|\u53f0\u6771|taiwan).{0,24}"
    r"(?:\u91e3\u9b5a|\u91e3\u9ede|\u91e3\u5834|\u6d77\u91e3|\u6eaa\u91e3|fishing).{0,24}"
    r"(?:\u5730\u9ede|\u63a8\u85a6|\u54ea\u88e1|\u53bb\u54ea|location|spot|place|where|recommend)",
    re.IGNORECASE,
)
OUTDOOR_PRODUCT_RECOMMENDATION_RE = re.compile(
    r"(?:\u5217\u51fa|\u63a8\u85a6|\u5efa\u8b70|\u6e96\u5099|\u9700\u8981|\u54ea\u4e9b|\u6e05\u55ae|recommend|suggest|prepare|need|list|checklist).{0,24}"
    r"(?:\u88dd\u5099|\u5668\u6750|\u5546\u54c1|\u7522\u54c1|\u7528\u54c1|gear|equipment|product|item|tackle)"
    r"|(?:\u88dd\u5099|\u5668\u6750|\u5546\u54c1|\u7522\u54c1|\u7528\u54c1|gear|equipment|product|item|tackle).{0,24}"
    r"(?:\u63a8\u85a6|\u5efa\u8b70|\u6e96\u5099|\u9700\u8981|\u6e05\u55ae|recommend|suggest|prepare|need|list|checklist)",
    re.IGNORECASE,
)
OUTDOOR_ADVICE_BUSINESS_RE = re.compile(
    r"(?:\u5eab\u5b58|\u73fe\u8ca8|\u6709\u8ca8|\u50f9\u683c|\u50f9\u9322|\u5831\u50f9|vip|sku|"
    r"inventory|stock|in[\s-]?stock|price|quote|quotation)",
    re.IGNORECASE,
)
TASTING_NOTE_TOKENS.update({"品飲紀錄", "試飲紀錄", "香味", "酒體", "酸度", "單寧", "餘韻", "描述味道"})
VINEYARD_LOOKUP_TOKENS.update({"園區", "地塊", "田塊", "風土名園"})
TERROIR_TOKENS.update({"差異", "比較", "風土", "村莊", "一級園", "特級園", "土壤", "產區"})
BRAND_PROFILE_TOKENS.update({"詳細", "介紹", "描述", "酒莊", "背景", "故事", "葡萄園", "產區", "釀造", "技巧", "歷史"})
REGION_ALIASES.update(
    {
        "Burgundy": (*REGION_ALIASES["Burgundy"], "勃艮第"),
        "Champagne": (*REGION_ALIASES["Champagne"], "香槟"),
    }
)


class AnalysisService:
    def __init__(
        self,
        attachment_understanding_service: Optional[AttachmentUnderstandingService] = None,
        url_product_lookup_service: Optional[UrlProductLookupService] = None,
    ) -> None:
        self._attachment_understanding_service = (
            attachment_understanding_service or AttachmentUnderstandingService()
        )
        self._url_product_lookup_service = url_product_lookup_service or UrlProductLookupService()

    async def analyze(
        self,
        text: str,
        *,
        conn=None,
        domain: str = "alcohol",
        attachment: Optional[Dict[str, Any]] = None,
        prior_attachment_context: Optional[Dict[str, Any]] = None,
        url_inputs: Optional[List[str]] = None,
    ) -> AnalysisResult:
        intent = self._safe_detect_intent(text, domain=domain)
        query_variants, alias_filters = await self._safe_expand_aliases(conn, text)
        sanitized_alias_filters = self._sanitize_alias_filters(text, alias_filters or {})
        inferred_producer = self._infer_producer_from_query(text)
        producer_inferred = False
        if inferred_producer:
            existing_values = sanitized_alias_filters.get("producer")
            if isinstance(existing_values, str):
                existing_values = [existing_values]
            normalized_existing = [str(item).strip().lower() for item in (existing_values or []) if str(item).strip()]
            normalized_inferred = inferred_producer.strip().lower()
            if normalized_inferred and normalized_inferred not in normalized_existing:
                sanitized_alias_filters["producer"] = [inferred_producer]
                producer_inferred = True
        sanitized_variants = [text] if producer_inferred else self._sanitize_query_variants(text, query_variants, sanitized_alias_filters)
        normalized_variants = self._normalize_query_variants(text, sanitized_variants)
        normalized_url_inputs = self._normalize_url_inputs(url_inputs)
        primary_url = normalized_url_inputs[0] if normalized_url_inputs else None
        extract_first_url = getattr(self._url_product_lookup_service, "extract_first_url", None)
        inline_url = extract_first_url(text) if callable(extract_first_url) else None
        url_input_source = "structured" if normalized_url_inputs else (
            "inline_text" if inline_url else None
        )
        analysis_text = self._build_analysis_text(text, primary_url)
        attachment_context = await self._attachment_understanding_service.understand(
            attachment,
            query=text,
            prior_context=prior_attachment_context,
        )
        prompt_category = self._infer_prompt_category(analysis_text)
        lookup_goal = None
        url_lookup: Dict[str, Any] = {}
        if prompt_category == "url_product_lookup":
            lookup_goal = self._url_product_lookup_service.infer_lookup_goal(analysis_text)
            url_lookup = await self._url_product_lookup_service.analyze_query(
                analysis_text,
                primary_url=primary_url,
            )
            if not lookup_goal:
                lookup_goal = str(url_lookup.get("lookup_goal") or "").strip() or None
            if (
                not lookup_goal
                and (
                    str(url_lookup.get("canonical_url") or "").strip()
                    or str(url_lookup.get("product_handle") or "").strip()
                )
            ):
                lookup_goal = "product_availability_from_url"
        if self._should_force_brand_profile(
            analysis_text,
            base_category=prompt_category,
            inferred_producer=inferred_producer,
        ):
            prompt_category = "brand_profile"
        if attachment_context:
            prompt_category = self._resolve_attachment_prompt_category(
                analysis_text,
                prompt_category,
                attachment_context,
            )
        entity_resolution = self._resolve_entity_context(text, sanitized_alias_filters)
        if (
            entity_resolution.get("canonical_entity_type") == "region_vintage"
            and prompt_category == "brand_profile"
        ):
            prompt_category = "vintage_region_overview"
        if entity_resolution.get("canonical_entity_type") == "region_vintage":
            sanitized_alias_filters = self._remove_region_vintage_producer_noise(
                sanitized_alias_filters,
                entity_resolution,
            )
            normalized_variants = self._normalize_query_variants(
                text,
                [
                    self._build_region_vintage_query_variant(entity_resolution),
                    *normalized_variants,
                ],
            )

        entity_hints = self._build_entity_hints(text, sanitized_alias_filters)
        if entity_resolution:
            entity_hints = self._merge_entity_resolution_hints(entity_hints, entity_resolution)
        if inferred_producer and not self._normalize_hint(entity_hints.get("producer")):
            entity_hints["producer"] = inferred_producer
        attachment_entity_hints = (
            attachment_context.get("entity_hints")
            if isinstance(attachment_context.get("entity_hints"), dict)
            else {}
        )
        if attachment_entity_hints:
            entity_hints = self._merge_entity_hints(entity_hints, attachment_entity_hints)
        url_entity_hints = (
            url_lookup.get("entity_hints")
            if isinstance(url_lookup.get("entity_hints"), dict)
            else {}
        )
        if url_entity_hints:
            entity_hints = self._merge_entity_hints(url_entity_hints, entity_hints)
        retrieval_query = str(attachment_context.get("search_query") or "").strip() if attachment_context else ""
        if prompt_category == "url_product_lookup" and not retrieval_query:
            retrieval_query = str(url_lookup.get("search_query") or "").strip()
        if attachment_context and retrieval_query:
            normalized_variants = self._normalize_query_variants(
                retrieval_query,
                [retrieval_query, *normalized_variants],
            )
        authoritative_reason = self._determine_authoritative_reason(analysis_text, prompt_category)
        if prompt_category in {"critic_score_lookup", "source_validation"}:
            entity_hints, sanitized_alias_filters, normalized_variants = self._remove_critic_source_entities(
                text,
                entity_hints,
                sanitized_alias_filters,
                normalized_variants,
            )
            if intent.name == "QUOTE_LIST":
                intent = Intent(name="ASK_ALCOHOL_INFO", slots=intent.slots)
        return AnalysisResult(
            intent=intent,
            query_variants=normalized_variants,
            alias_filters=sanitized_alias_filters,
            entity_hints=entity_hints,
            entity_resolution=entity_resolution,
            attachment_context=attachment_context,
            url_lookup=url_lookup,
            url_inputs=normalized_url_inputs,
            primary_url=primary_url,
            url_input_source=url_input_source,
            lookup_goal=lookup_goal,
            retrieval_query=retrieval_query or None,
            prompt_category=prompt_category,
            needs_authoritative_sources=bool(authoritative_reason),
            authoritative_reason=authoritative_reason,
        )

    @classmethod
    def _remove_critic_source_entities(
        cls,
        text: str,
        entity_hints: Dict[str, Any],
        alias_filters: Dict[str, Any],
        query_variants: List[str],
    ) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
        cleaned_hints = dict(entity_hints or {})
        cleaned_aliases = dict(alias_filters or {})
        producer_values = cleaned_hints.get("producer")
        retained_producers = cls._sanitize_producer_values(text, producer_values)
        if retained_producers:
            cleaned_hints["producer"] = retained_producers[0] if len(retained_producers) == 1 else retained_producers
        else:
            cleaned_hints.pop("producer", None)
        alias_producers = cleaned_aliases.get("producer")
        retained_alias_producers = cls._sanitize_producer_values(text, alias_producers)
        if retained_alias_producers:
            cleaned_aliases["producer"] = retained_alias_producers
        else:
            cleaned_aliases.pop("producer", None)
        cleaned_variants = []
        for variant in query_variants or []:
            value = str(variant or "").strip()
            if not value:
                continue
            if cls._looks_like_list_string(value):
                continue
            cleaned_variants.append(value)
        return cleaned_hints, cleaned_aliases, cls._normalize_query_variants(text, cleaned_variants)

    @staticmethod
    def _normalize_url_inputs(url_inputs: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        for raw in url_inputs or []:
            value = str(raw or "").strip()
            if not value or value in normalized:
                continue
            normalized.append(value)
        return normalized

    @staticmethod
    def _build_analysis_text(text: str, primary_url: Optional[str]) -> str:
        base = str(text or "").strip()
        normalized_url = str(primary_url or "").strip()
        if not normalized_url:
            return base
        if normalized_url in base:
            return base
        return f"{base}\n{normalized_url}".strip()

    def _safe_detect_intent(self, text: str, *, domain: str) -> Intent:
        try:
            payload = _detect_intent(text, domain=domain)  # type: ignore
            if isinstance(payload, dict):
                return Intent(
                    name=str(payload.get("name") or "FREE_CHAT"),
                    slots=payload.get("slots") or {},
                )
        except Exception as exc:
            logger.warning("Intent detection failed: %s", exc)
        fallback = self._fallback_intent(text)
        return Intent(name=fallback, slots={})

    @staticmethod
    def _fallback_intent(text: str) -> str:
        lowered = (text or "").lower()
        alcohol = any(
            token in lowered
            for token in [
                "wine",
                "beer",
                "whisky",
                "whiskey",
                "rum",
                "gin",
                "vodka",
                "sake",
                "tequila",
                "mezcal",
                "cocktail",
                "酒",
                "香檳",
                "紅酒",
                "白酒",
            ]
        )
        return "ASK_ALCOHOL_INFO" if alcohol else "FREE_CHAT"

    async def _safe_expand_aliases(
        self,
        conn,
        query: str,
    ) -> Tuple[List[str], Dict[str, Any]]:
        owned_conn = None
        try:
            if conn is None:
                owned_conn = await db.get_conn()
                conn = owned_conn
            if conn is None:
                return [query], {}
            return await _expand_aliases(conn, query)  # type: ignore
        except Exception as exc:
            logger.warning("Alias expansion failed: %s", exc)
            return [query], {}
        finally:
            if owned_conn:
                await owned_conn.close()

    @staticmethod
    def _normalize_query_variants(text: str, variants: Optional[List[str]]) -> List[str]:
        normalized: List[str] = []
        for item in variants or []:
            value = (item or "").strip()
            if value and value not in normalized:
                normalized.append(value)
        if text and text not in normalized:
            normalized.insert(0, text)
        return normalized

    @staticmethod
    def _sanitize_alias_filters(text: str, alias_filters: Dict[str, Any]) -> Dict[str, Any]:
        sanitized = {
            key: value
            for key, value in (alias_filters or {}).items()
            if key in ALLOWED_ALIAS_FILTER_KEYS
        }
        producer_values = sanitized.get("producer")
        sanitized_producer = AnalysisService._sanitize_producer_values(text, producer_values)
        if sanitized_producer:
            sanitized["producer"] = sanitized_producer
        elif "producer" in sanitized:
            sanitized.pop("producer", None)
        return sanitized

    @staticmethod
    def _sanitize_query_variants(
        text: str,
        query_variants: Optional[List[str]],
        alias_filters: Dict[str, Any],
    ) -> List[str]:
        variants = [str(item).strip() for item in (query_variants or []) if str(item).strip()]
        producer_values = alias_filters.get("producer")
        if isinstance(producer_values, str):
            producer_values = [producer_values]
        producer_values = [str(item).strip().lower() for item in (producer_values or []) if str(item).strip()]
        if not producer_values:
            return [text] if text else variants
        filtered = [
            variant
            for variant in variants
            if any(producer in variant.lower() for producer in producer_values)
        ]
        return filtered or ([text] if text else variants[:1])

    @staticmethod
    def _sanitize_producer_values(text: str, producer_values: Any) -> List[str]:
        values = producer_values if isinstance(producer_values, list) else [producer_values]
        normalized_values = []
        for item in values:
            candidate = str(item).strip()
            if not candidate:
                continue
            if candidate.lower() in EMPTY_ENTITY_SENTINELS:
                continue
            if AnalysisService._looks_like_producer_noise(candidate):
                continue
            normalized_values.append(candidate)
        if not normalized_values:
            return []

        query_tokens = AnalysisService._extract_query_entity_tokens(text)
        if not query_tokens:
            return normalized_values[:5]

        scored: List[Tuple[int, str]] = []
        for candidate in normalized_values:
            score = AnalysisService._producer_candidate_score(query_tokens, candidate)
            if score > 0:
                scored.append((score, candidate))
        if not scored:
            return []

        max_score = max(score for score, _ in scored)
        minimum_score = max_score
        if len(query_tokens) >= 2:
            minimum_score = max(max_score, 2)
        retained = [candidate for score, candidate in scored if score >= minimum_score]
        deduped: List[str] = []
        for candidate in retained:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped[:5]

    @staticmethod
    def _extract_query_entity_tokens(text: str) -> List[str]:
        lowered = (text or "").lower()
        tokens = re.findall(r"[a-z0-9]+", lowered)
        return [
            token
            for token in tokens
            if len(token) > 1 and token not in ALIAS_QUERY_STOP_WORDS
        ]

    @staticmethod
    def _producer_candidate_score(query_tokens: List[str], candidate: str) -> int:
        candidate_norm = " ".join((candidate or "").lower().split())
        if not candidate_norm:
            return 0
        candidate_tokens = re.findall(r"[a-z0-9]+", candidate_norm)
        if not candidate_tokens:
            return 0
        overlap = sum(1 for token in query_tokens if token in candidate_tokens)
        if overlap == 0:
            return 0
        if " ".join(query_tokens) in candidate_norm:
            overlap += 2
        return overlap

    @staticmethod
    def _infer_producer_from_query(text: str) -> Optional[str]:
        raw = " ".join((text or "").split()).strip()
        if not raw:
            return None
        patterns = [
            r"\b((?:YS|Champagne|Chateau|Château|Clos|Maison)\s+[A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){0,5})\b",
            r"(?:about|for|of)\s+([A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){0,5})",
            r"(?:news about|source for|website for|site for)\s+([A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){0,5})",
            r"(?:介紹|關於|官網|官方網站|來源|網址|網站)\s*([A-Z][A-Za-z'&.\-]+(?:\s+[A-Z][A-Za-z'&.\-]+){0,5})",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = re.sub(r"[?.!,;:]+$", "", match.group(1).strip())
            if AnalysisService._looks_like_producer_noise(candidate):
                continue
            tokens = re.findall(r"[A-Za-z0-9]+", candidate.lower())
            meaningful = [
                token
                for token in tokens
                if len(token) > 1 and token not in ALIAS_QUERY_STOP_WORDS
            ]
            if len(meaningful) >= 2:
                return candidate
        return None

    @staticmethod
    def _looks_like_producer_noise(value: Any) -> bool:
        normalized = " ".join(str(value or "").lower().split())
        if not normalized:
            return False
        return any(token in normalized for token in PRODUCER_NOISE_TOKENS)

    @staticmethod
    def _looks_like_list_string(value: Any) -> bool:
        text = str(value or "").strip().strip("\"'")
        return text.startswith("[")

    @staticmethod
    def _infer_prompt_category(text: str) -> str:
        normalized = (text or "").strip().lower()
        if not normalized:
            return "general_chat"
        if AnalysisService._has_explicit_url(normalized):
            return "url_product_lookup"
        if AnalysisService._looks_like_outdoor_product_recommendation_query(text):
            return "quote_recommendation"
        if AnalysisService._looks_like_outdoor_advice_query(text):
            return "general_chat"
        if AnalysisService._contains_any(normalized, QUOTE_TOKENS):
            return "quote_recommendation"
        if AnalysisService._looks_like_internal_rag_only_query(normalized):
            return "internal_rag_only_validation"
        if AnalysisService._looks_like_source_hierarchy_conflict_query(normalized):
            return "source_hierarchy_conflict"
        if (
            AnalysisService._contains_any(normalized, CRITIC_TOKENS)
            and AnalysisService._contains_any(
                normalized,
                {
                    "review",
                    "reviews",
                    "score",
                    "scores",
                    "rating",
                    "ratings",
                    "tasting note",
                    "tasting notes",
                    "drinking window",
                    "酒評",
                    "評分",
                    "分數",
                },
            )
        ):
            return "exact_review_lookup"
        source_validation_tokens = {
            "citation",
            "citations",
            "source",
            "sources",
            "reference",
            "references",
            "引用",
            "來源",
            "資訊來源",
            "資料來源",
            "文件",
            "哪份文件",
            "第幾頁",
            "頁碼",
            "第幾行",
            "行號",
            "哪個網站",
            "引用哪個網站",
        }
        if AnalysisService._contains_any(normalized, source_validation_tokens):
            return "source_validation"
        if AnalysisService._looks_like_url_query(normalized):
            return "url_product_lookup"
        if AnalysisService._contains_any(normalized, CRITIC_TOKENS):
            return "critic_score_lookup"
        if AnalysisService._contains_any(normalized, TASTING_NOTE_TOKENS):
            return "tasting_note_generation"
        if AnalysisService._looks_like_producer_ranking(normalized):
            return "producer_ranking"
        if AnalysisService._contains_any(normalized, IMAGE_TOKENS):
            return "image_product_lookup"
        if AnalysisService._contains_any(normalized, INVENTORY_TOKENS):
            return "inventory_lookup"
        if AnalysisService._looks_like_region_vintage_overview(normalized):
            return "vintage_region_overview"
        if AnalysisService._contains_any(normalized, BRAND_PROFILE_TOKENS | BRAND_PROFILE_TOKENS_ZH):
            inferred_producer = AnalysisService._infer_producer_from_query(text)
            if inferred_producer and AnalysisService._count_token_matches(
                normalized,
                BRAND_PROFILE_TOKENS | BRAND_PROFILE_TOKENS_ZH,
            ) >= 2:
                return "brand_profile"
        if AnalysisService._contains_any(normalized, TERROIR_TOKENS):
            return "terroir_comparison"
        if AnalysisService._looks_like_vineyard_lookup(normalized):
            return "vineyard_lookup"
        if AnalysisService._contains_any(normalized, BRAND_PROFILE_TOKENS | BRAND_PROFILE_TOKENS_ZH):
            return "brand_profile"
        return "general_chat"

    @staticmethod
    def _looks_like_internal_rag_only_query(normalized: str) -> bool:
        internal_markers = (
            "internal rag",
            "internal sources",
            "internal source",
            "internal documents",
            "internal docs",
            "internal corpus",
            "rag sources",
            "rag source",
        )
        restrictive_markers = (
            "only",
            "using only",
            "answer using only",
            "based only",
            "use only",
            "只用",
            "僅用",
            "只使用",
            "僅使用",
        )
        return any(marker in normalized for marker in internal_markers) and any(
            marker in normalized for marker in restrictive_markers
        )

    @staticmethod
    def _looks_like_outdoor_advice_query(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        return bool(
            (OUTDOOR_LOCATION_ADVICE_RE.search(raw) or OUTDOOR_ADVICE_TOPIC_RE.search(raw))
            and OUTDOOR_ADVICE_REQUEST_RE.search(raw)
            and not OUTDOOR_PRODUCT_RECOMMENDATION_RE.search(raw)
            and not OUTDOOR_ADVICE_BUSINESS_RE.search(raw)
        )

    @staticmethod
    def _looks_like_outdoor_location_advice_query(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        return bool(
            OUTDOOR_LOCATION_ADVICE_RE.search(raw)
            and not OUTDOOR_PRODUCT_RECOMMENDATION_RE.search(raw)
            and not OUTDOOR_ADVICE_BUSINESS_RE.search(raw)
        )

    @staticmethod
    def _looks_like_outdoor_product_recommendation_query(text: str) -> bool:
        raw = str(text or "").strip()
        if not raw:
            return False
        return bool(
            OUTDOOR_ADVICE_TOPIC_RE.search(raw)
            and OUTDOOR_PRODUCT_RECOMMENDATION_RE.search(raw)
        )

    @staticmethod
    def _looks_like_source_hierarchy_conflict_query(normalized: str) -> bool:
        has_old_source = any(
            marker in normalized
            for marker in (
                "older book",
                "old book",
                "book description",
                "reference book",
                "historical description",
            )
        )
        has_current_source = any(
            marker in normalized
            for marker in (
                "newer producer",
                "producer website",
                "official website",
                "current erp",
                "current cerp",
                "erp product data",
                "cerp product data",
                "current product data",
                "current product facts",
            )
        )
        asks_control = any(
            marker in normalized
            for marker in (
                "which should control",
                "which controls",
                "should control",
                "control for current",
                "conflicts with",
                "conflict with",
                "conflict",
                "override",
            )
        )
        return has_old_source and has_current_source and asks_control

    @staticmethod
    def _looks_like_vineyard_lookup(normalized: str) -> bool:
        if not AnalysisService._contains_any(normalized, VINEYARD_LOOKUP_TOKENS):
            return False
        broad_profile_tokens = {
            "background",
            "history",
            "story",
            "winemaking",
            "producer",
            "winery",
            "estate",
            "背景",
            "歷史",
            "故事",
            "釀造",
            "酒莊",
        }
        if AnalysisService._count_token_matches(normalized, broad_profile_tokens) >= 2:
            return False
        return True

    @staticmethod
    def _looks_like_producer_ranking(normalized: str) -> bool:
        if not AnalysisService._contains_any(normalized, PRODUCER_RANKING_TOKENS):
            return False
        return any(
            token in normalized
            for token in {
                "producer",
                "producers",
                "ys",
                "yss",
                "estate",
                "estates",
                "winery",
                "wineries",
                "\u9152\u838a",
                "\u540d\u5bb6",
                "\u540d\u838a",
            }
        )

    @staticmethod
    def _build_entity_hints(text: str, alias_filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        hints: Dict[str, Any] = {}
        filters = alias_filters or {}
        for key in ("producer", "region", "style", "classification", "grape", "grape_varieties"):
            value = filters.get(key)
            if isinstance(value, list):
                normalized = [str(item).strip() for item in value if str(item).strip()]
                if normalized:
                    hints[key] = normalized[0] if len(normalized) == 1 else normalized
            elif isinstance(value, str) and value.strip():
                hints[key] = value.strip()

        lowered = (text or "").lower()
        region_aliases = {
            "champagne": ("champagne", "香檳"),
            "burgundy": ("burgundy", "bourgogne", "勃根地"),
            "bordeaux": ("bordeaux", "波爾多"),
            "alsace": ("alsace", "阿爾薩斯"),
            "loire": ("loire", "羅亞爾", "羅亞爾河"),
            "meursault": ("meursault", "默爾索"),
        }
        region_aliases.update(
            {
                "champagne": (*region_aliases.get("champagne", ()), "香檳", "香槟"),
                "burgundy": (*region_aliases.get("burgundy", ()), "布根地", "勃艮第"),
                "bordeaux": (*region_aliases.get("bordeaux", ()), "波爾多", "波尔多"),
                "alsace": (*region_aliases.get("alsace", ()), "阿爾薩斯", "阿尔萨斯"),
                "loire": (*region_aliases.get("loire", ()), "羅瓦河", "卢瓦尔"),
                "meursault": (*region_aliases.get("meursault", ()), "默爾索", "默尔索"),
            }
        )
        if "region" not in hints:
            for normalized_region, aliases in region_aliases.items():
                if any(alias in lowered for alias in aliases):
                    hints["region"] = normalized_region
                    break
        if "vintage" not in hints:
            vintage = AnalysisService._extract_vintage(text)
            if vintage:
                hints["vintage"] = vintage
        return hints

    @staticmethod
    def _looks_like_region_vintage_overview(normalized_text: str) -> bool:
        if not normalized_text:
            return False
        has_region = any(
            alias.lower() in normalized_text
            for aliases in REGION_ALIASES.values()
            for alias in aliases
        )
        if not has_region:
            return False
        if not AnalysisService._extract_vintage(normalized_text):
            return False
        return AnalysisService._contains_any(normalized_text, REGION_VINTAGE_OVERVIEW_TOKENS)

    @staticmethod
    def _extract_vintage(text: str) -> Optional[str]:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(text or ""))
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def _resolve_entity_context(text: str, alias_filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        lowered = str(text or "").lower()
        vintage = AnalysisService._extract_vintage(text)
        canonical_region = None
        raw_mentions: List[str] = []
        for region, aliases in REGION_ALIASES.items():
            for alias in aliases:
                if alias.lower() in lowered:
                    canonical_region = region
                    raw_mentions.append(alias)
            if canonical_region:
                break
        if not (canonical_region and vintage):
            return {}

        color_scope = []
        if re.search(r"\bred\b|\u7d05\u9152|\u7d05", lowered):
            color_scope.append("red")
        if re.search(r"\bwhite\b|\u767d\u9152|\u767d", lowered):
            color_scope.append("white")

        return {
            "canonical_entity_type": "region_vintage",
            "canonical_region": canonical_region,
            "vintage": vintage,
            "locked": True,
            "source": "phase1_region_vintage_normalizer",
            "raw_mentions": raw_mentions,
            "color_scope": color_scope,
            "dropped_alias_filters": AnalysisService._region_vintage_noise_filters(
                alias_filters or {},
                canonical_region=canonical_region,
            ),
        }

    @staticmethod
    def _region_vintage_noise_filters(
        alias_filters: Dict[str, Any],
        *,
        canonical_region: str,
    ) -> Dict[str, Any]:
        producer_values = alias_filters.get("producer")
        values = producer_values if isinstance(producer_values, list) else [producer_values]
        region_token = canonical_region.lower()
        dropped = [
            str(item).strip()
            for item in values
            if str(item or "").strip() and region_token in str(item).lower()
        ]
        return {"producer": dropped} if dropped else {}

    @staticmethod
    def _remove_region_vintage_producer_noise(
        alias_filters: Dict[str, Any],
        entity_resolution: Dict[str, Any],
    ) -> Dict[str, Any]:
        dropped = (
            entity_resolution.get("dropped_alias_filters")
            if isinstance(entity_resolution.get("dropped_alias_filters"), dict)
            else {}
        )
        dropped_producers = {str(item).strip() for item in dropped.get("producer") or [] if str(item).strip()}
        if not dropped_producers:
            return alias_filters
        normalized = dict(alias_filters or {})
        producer_values = normalized.get("producer")
        values = producer_values if isinstance(producer_values, list) else [producer_values]
        retained = [
            str(item).strip()
            for item in values
            if str(item or "").strip() and str(item).strip() not in dropped_producers
        ]
        if retained:
            normalized["producer"] = retained
        else:
            normalized.pop("producer", None)
        return normalized

    @staticmethod
    def _merge_entity_resolution_hints(
        entity_hints: Dict[str, Any],
        entity_resolution: Dict[str, Any],
    ) -> Dict[str, Any]:
        hints = dict(entity_hints or {})
        if entity_resolution.get("canonical_entity_type") == "region_vintage":
            hints["region"] = entity_resolution.get("canonical_region") or hints.get("region")
            hints["vintage"] = entity_resolution.get("vintage") or hints.get("vintage")
            if entity_resolution.get("locked"):
                hints["entity_lock"] = "region_vintage"
            colors = entity_resolution.get("color_scope")
            if isinstance(colors, list) and colors:
                hints["color_scope"] = colors
        return hints

    @staticmethod
    def _build_region_vintage_query_variant(entity_resolution: Dict[str, Any]) -> str:
        region = str(entity_resolution.get("canonical_region") or "").strip()
        vintage = str(entity_resolution.get("vintage") or "").strip()
        colors = entity_resolution.get("color_scope") if isinstance(entity_resolution.get("color_scope"), list) else []
        color_text = " ".join(str(item) for item in colors if item)
        return " ".join(
            part
            for part in [region, vintage, color_text, "vintage characteristics"]
            if part
        ).strip()

    @staticmethod
    def _determine_authoritative_reason(text: str, prompt_category: str) -> Optional[str]:
        lowered = (text or "").lower()
        if prompt_category in {"internal_rag_only_validation", "source_hierarchy_conflict"}:
            return None
        if prompt_category == "source_validation":
            return "source_validation"
        if AnalysisService._contains_any(lowered, LATEST_INFO_TOKENS):
            return "latest_info"
        profile = get_behavior_profile(prompt_category)
        if profile.get("source_policy") == "authoritative_external_required":
            return "authoritative_required"
        if AnalysisService._contains_any(lowered, SOURCE_TOKENS):
            return "authoritative_required"
        return None

    @staticmethod
    def _normalize_hint(value: Any) -> Optional[str]:
        if isinstance(value, list):
            for item in value:
                normalized = AnalysisService._normalize_hint(item)
                if normalized:
                    return normalized
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        if lowered in EMPTY_ENTITY_SENTINELS:
            return None
        return normalized

    @staticmethod
    def _should_force_brand_profile(
        text: str,
        *,
        base_category: str,
        inferred_producer: Optional[str],
    ) -> bool:
        if base_category not in {"general_chat", "brand_profile"}:
            return False
        if not inferred_producer:
            return False
        if not re.search(r"\b(?:YS|Champagne|Chateau|Château|Clos|Maison)\b", inferred_producer):
            return False
        normalized = (text or "").strip().lower()
        return AnalysisService._count_token_matches(normalized, BRAND_PROFILE_TOKENS | BRAND_PROFILE_TOKENS_ZH) >= 2

    @staticmethod
    def _count_token_matches(text: str, tokens: set[str]) -> int:
        count = 0
        for token in tokens:
            if token and token in text:
                count += 1
        return count

    @staticmethod
    def _merge_entity_hints(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (extra or {}).items():
            if not isinstance(value, str):
                continue
            normalized = value.strip()
            if not normalized or normalized.lower() in EMPTY_ENTITY_SENTINELS:
                continue
            existing = merged.get(key)
            if isinstance(existing, str) and existing.strip().lower() in EMPTY_ENTITY_SENTINELS:
                existing = ""
            if not existing:
                merged[key] = normalized
        return merged

    @staticmethod
    def _resolve_attachment_prompt_category(
        text: str,
        base_category: str,
        attachment_context: Dict[str, Any],
    ) -> str:
        attachment_type = str(attachment_context.get("type") or "").strip().lower()
        match_intent = str(attachment_context.get("match_intent") or "").strip().lower()
        if attachment_type == "image":
            if match_intent == "cerp_match":
                return "image_product_lookup"
            if base_category == "general_chat":
                return "image_product_lookup"
        return base_category

    @staticmethod
    def _looks_like_url_query(normalized_text: str) -> bool:
        if AnalysisService._has_explicit_url(normalized_text):
            return True
        if AnalysisService._contains_any(normalized_text, QUOTE_TOKENS):
            return False
        return AnalysisService._contains_any(normalized_text, URL_TOKENS)

    @staticmethod
    def _has_explicit_url(normalized_text: str) -> bool:
        return bool(re.search(r"https?://|www\.", normalized_text or ""))

    @staticmethod
    def _contains_any(text: str, tokens: set[str]) -> bool:
        return any(token in text for token in tokens)
