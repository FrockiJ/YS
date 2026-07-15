from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


NEED_PROFILE_VERSION = "outdoor-v1"

_ACTIVITY_TERMS = {
    "hiking": ("登山", "健行", "爬山", "百岳", "縱走", "hiking", "trekking", "mountain"),
    "camping": ("露營", "野營", "camping", "camp"),
    "fishing": ("釣魚", "路亞", "溪釣", "海釣", "fishing", "angling"),
    "outdoor": ("戶外", "野外", "outdoor"),
}

_CATEGORY_RULES = {
    "rain_protection": ("雨", "雨季", "防水", "潮濕", "颱風", "rain", "waterproof", "wet"),
    "shelter": ("帳篷", "天幕", "遮蔽", "過夜", "紮營", "tent", "shelter", "tarp"),
    "sleeping_gear": ("睡袋", "睡墊", "保暖", "低溫", "寒冷", "sleep", "warm", "cold"),
    "lighting": ("照明", "頭燈", "夜間", "天黑", "lighting", "headlamp", "night"),
    "cooking_water": ("炊煮", "爐具", "飲水", "水壺", "煮食", "stove", "cook", "water"),
    "storage_packs": ("背包", "收納", "負重", "行李", "pack", "backpack", "storage"),
    "power": ("電力", "充電", "行動電源", "太陽能", "power", "charge", "solar"),
    "safety_repair": ("安全", "急救", "求生", "維修", "修補", "迷路", "safety", "repair", "first aid"),
    "fishing_gear": ("釣竿", "捲線器", "魚線", "魚鉤", "路亞", "rod", "reel", "lure", "hook", "line"),
}

_DEFAULT_CATEGORIES = {
    "hiking": ["rain_protection", "storage_packs", "lighting", "safety_repair"],
    "camping": ["shelter", "sleeping_gear", "lighting", "cooking_water", "safety_repair"],
    "fishing": ["fishing_gear", "storage_packs", "safety_repair"],
    "outdoor": ["rain_protection", "lighting", "safety_repair"],
}

_KNOWLEDGE_TO_PRODUCT_RE = re.compile(
    r"(?:如何準備|怎麼準備|注意事項|要帶什麼|需要什麼|安全|風險|雨季|低溫|過夜|行前)|"
    r"\b(?:prepare|preparation|checklist|safety|risk|rainy season|cold weather|overnight)\b",
    re.IGNORECASE,
)
_TOPIC_SHIFT_RE = re.compile(
    r"(?:換個話題|換話題|另外一件事|不談這個|重新開始)|\b(?:new topic|change topic|start over)\b",
    re.IGNORECASE,
)


def _empty_profile() -> Dict[str, Any]:
    return {
        "activity": None,
        "use_case": None,
        "location": None,
        "duration": None,
        "party_size": None,
        "weather": [],
        "budget": None,
        "categories": [],
        "required_features": [],
        "excluded_features": [],
        "preferred_brands": [],
        "owned_gear": [],
        "quantity": None,
    }


def _unique(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


@dataclass(frozen=True)
class ProductNeedResult:
    profile: Dict[str, Any]
    eligible: bool
    explicit_product_intent: bool
    preview_categories: List[str]


class ProductNeedExtractor:
    """Builds a product-need snapshot from user facts, never from generated answer text."""

    version = NEED_PROFILE_VERSION

    def extract(
        self,
        message: str,
        *,
        history: Optional[Sequence[Dict[str, Any]]] = None,
        context_state: Optional[Dict[str, Any]] = None,
        rag_summaries: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> ProductNeedResult:
        text = str(message or "").strip()
        history = list(history or [])[-12:]
        inherited = self._latest_profile(history) or self._profile_from_context(context_state)
        topic_shift = bool(_TOPIC_SHIFT_RE.search(text))
        profile = _empty_profile() if topic_shift or not inherited else copy.deepcopy(inherited)
        for key, default in _empty_profile().items():
            profile.setdefault(key, copy.deepcopy(default))

        prior_activity = str(profile.get("activity") or "")
        detected_activity = self._detect_activity(text)
        if detected_activity and prior_activity and detected_activity != prior_activity:
            profile = _empty_profile()
        if detected_activity:
            profile["activity"] = detected_activity

        profile["location"] = self._extract_location(text) or profile.get("location")
        profile["duration"] = self._extract_duration(text) or profile.get("duration")
        profile["party_size"] = self._extract_party_size(text) or profile.get("party_size")
        profile["quantity"] = self._extract_quantity(text) or profile.get("quantity")
        profile["weather"] = _unique([*(profile.get("weather") or []), *self._extract_weather(text)])

        budget = self._extract_budget(text)
        if budget:
            profile["budget"] = budget
        elif re.search(r"更便宜|便宜一點|預算降低|cheaper|lower budget", text, re.IGNORECASE):
            current_budget = profile.get("budget") if isinstance(profile.get("budget"), dict) else None
            if current_budget and current_budget.get("max"):
                profile["budget"] = {
                    **current_budget,
                    "max": round(float(current_budget["max"]) * 0.8, 2),
                }
            else:
                prior_price = self._latest_result_price(history)
                if prior_price is not None:
                    profile["budget"] = {
                        "min": None,
                        "max": round(prior_price * 0.8, 2),
                        "currency": "TWD",
                    }

        categories = self._detect_categories(text)
        if not categories and profile.get("activity") and not profile.get("categories"):
            categories = list(_DEFAULT_CATEGORIES.get(str(profile["activity"]), []))
        profile["categories"] = _unique([*(profile.get("categories") or []), *categories])
        profile["required_features"] = _unique(
            [*(profile.get("required_features") or []), *self._extract_required_features(text)]
        )
        profile["excluded_features"] = _unique(
            [*(profile.get("excluded_features") or []), *self._extract_exclusions(text, history)]
        )
        profile["preferred_brands"] = _unique(
            [*(profile.get("preferred_brands") or []), *self._extract_preferred_brands(text)]
        )
        profile["owned_gear"] = _unique([*(profile.get("owned_gear") or []), *self._extract_owned_gear(text)])

        if text:
            profile["use_case"] = self._build_use_case(text, profile)

        product_context = bool(
            profile.get("activity")
            or profile.get("categories")
            or re.search(r"戶外|登山|露營|釣魚|裝備|器材|outdoor|hiking|camping|fishing|gear", text, re.IGNORECASE)
        )
        bridgeable_knowledge = bool(product_context and _KNOWLEDGE_TO_PRODUCT_RE.search(text))
        eligible = bridgeable_knowledge

        # RAG may refine generic categories, but it may not introduce user facts.
        if eligible and rag_summaries:
            rag_text = " ".join(str(item.get("summary") or item.get("text") or "") for item in rag_summaries if isinstance(item, dict))
            profile["categories"] = _unique([*profile.get("categories", []), *self._detect_categories(rag_text)])

        return ProductNeedResult(
            profile=profile,
            eligible=eligible,
            # Kept in the public result for compatibility. Routing is exclusively
            # owned by ProductIntentAnalysisService.
            explicit_product_intent=False,
            preview_categories=list(profile.get("categories") or [])[:6],
        )

    @staticmethod
    def _profile_from_context(context_state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not isinstance(context_state, dict):
            return None
        profile = context_state.get("product_need_profile")
        if not isinstance(profile, dict) or not any(value not in (None, "", [], {}) for value in profile.values()):
            return None
        return copy.deepcopy(profile)

    @staticmethod
    def _latest_profile(history: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for item in reversed(history):
            metadata = item.get("metadata") if isinstance(item, dict) else None
            if not isinstance(metadata, dict):
                continue
            bridge = metadata.get("product_bridge")
            profile = bridge.get("need_profile") if isinstance(bridge, dict) and bridge.get("eligible") else None
            if isinstance(profile, dict) and any(value not in (None, "", [], {}) for value in profile.values()):
                return copy.deepcopy(profile)
        return None

    @staticmethod
    def _detect_activity(text: str) -> Optional[str]:
        lowered = text.casefold()
        for activity, terms in _ACTIVITY_TERMS.items():
            if any(term.casefold() in lowered for term in terms):
                return activity
        if re.search(r"玉山|雪山|合歡山|百岳|步道|山徑", text):
            return "hiking"
        return None

    @staticmethod
    def _detect_categories(text: str) -> List[str]:
        lowered = text.casefold()
        return [name for name, terms in _CATEGORY_RULES.items() if any(term.casefold() in lowered for term in terms)]

    @staticmethod
    def _extract_location(text: str) -> Optional[str]:
        known = re.search(r"(玉山|雪山|合歡山|阿里山|陽明山|太魯閣|墾丁|日月潭|台灣|臺灣)", text)
        if known:
            return known.group(1)
        english = re.search(r"\b(?:at|in|near)\s+([A-Z][A-Za-z\- ]{2,40})", text)
        return english.group(1).strip() if english else None

    @staticmethod
    def _extract_duration(text: str) -> Optional[Dict[str, Any]]:
        match = re.search(r"(\d+)\s*(天|日|晚|小時|hours?|days?|nights?)", text, re.IGNORECASE)
        if not match:
            return None
        return {"value": int(match.group(1)), "unit": match.group(2).lower()}

    @staticmethod
    def _extract_party_size(text: str) -> Optional[int]:
        match = re.search(r"(\d+)\s*(?:人|位|people|persons?)", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_quantity(text: str) -> Optional[int]:
        match = re.search(r"(?:數量|要|需要|買|quantity)\s*(\d+)\s*(?:個|件|組|套|支|頂|pcs?)?", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_weather(text: str) -> List[str]:
        rules = {
            "rain": ("雨", "雨季", "降雨", "rain"),
            "wind": ("風大", "強風", "wind"),
            "cold": ("低溫", "寒冷", "冷", "cold"),
            "hot": ("高溫", "炎熱", "熱", "hot"),
            "humid": ("潮濕", "濕氣", "humid"),
        }
        lowered = text.casefold()
        return [key for key, terms in rules.items() if any(term.casefold() in lowered for term in terms)]

    @staticmethod
    def _extract_budget(text: str) -> Optional[Dict[str, Any]]:
        range_match = re.search(
            r"(?:NT\$|NTD|新台幣|台幣|臺幣|預算)?\s*([\d,]+)\s*(?:到|至|[-~～])\s*(?:NT\$|NTD)?\s*([\d,]+)",
            text,
            re.IGNORECASE,
        )
        if range_match:
            return {
                "min": float(range_match.group(1).replace(",", "")),
                "max": float(range_match.group(2).replace(",", "")),
                "currency": "TWD",
            }
        max_match = re.search(
            r"(?:預算|上限|不要超過|低於|under|budget)\s*(?:NT\$|NTD|新台幣|台幣|臺幣)?\s*([\d,]+)",
            text,
            re.IGNORECASE,
        )
        if max_match:
            return {"min": None, "max": float(max_match.group(1).replace(",", "")), "currency": "TWD"}
        return None

    @staticmethod
    def _extract_required_features(text: str) -> List[str]:
        features = []
        for label, terms in {
            "waterproof": ("防水", "waterproof"),
            "lightweight": ("輕量", "輕便", "lightweight"),
            "windproof": ("防風", "windproof"),
            "compact": ("小巧", "好收納", "compact"),
            "warm": ("保暖", "warm"),
        }.items():
            if any(term.casefold() in text.casefold() for term in terms):
                features.append(label)
        return features

    @staticmethod
    def _extract_exclusions(text: str, history: Sequence[Dict[str, Any]]) -> List[str]:
        exclusions = []
        for match in re.finditer(r"(?:不要|排除|避免|不需要|without|exclude)\s*([^，。,.!?]{1,30})", text, re.IGNORECASE):
            value = match.group(1).strip()
            if value and value not in {"這個品牌", "那個品牌", "品牌"}:
                exclusions.append(value)
        if re.search(r"不要(?:這個|那個)?品牌|different brand|exclude that brand", text, re.IGNORECASE):
            brand = ProductNeedExtractor._latest_result_brand(history)
            if brand:
                exclusions.append(f"brand:{brand}")
        return exclusions

    @staticmethod
    def _latest_result_brand(history: Sequence[Dict[str, Any]]) -> Optional[str]:
        for item in reversed(history):
            metadata = item.get("metadata") if isinstance(item, dict) else None
            results = metadata.get("product_results") if isinstance(metadata, dict) else None
            if isinstance(results, list) and results:
                brand = results[0].get("brand") if isinstance(results[0], dict) else None
                if brand:
                    return str(brand).strip()
        return None

    @staticmethod
    def _latest_result_price(history: Sequence[Dict[str, Any]]) -> Optional[float]:
        for item in reversed(history):
            metadata = item.get("metadata") if isinstance(item, dict) else None
            results = metadata.get("product_results") if isinstance(metadata, dict) else None
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                try:
                    price = float(result.get("price"))
                except (TypeError, ValueError):
                    continue
                if price > 0:
                    return price
        return None

    @staticmethod
    def _extract_preferred_brands(text: str) -> List[str]:
        match = re.search(r"(?:偏好|喜歡|指定|prefer)\s*(?:品牌)?\s*([A-Za-z][A-Za-z0-9 &\-]{1,30})", text, re.IGNORECASE)
        return [match.group(1).strip()] if match else []

    @staticmethod
    def _extract_owned_gear(text: str) -> List[str]:
        match = re.search(r"(?:已有|已經有|自備|我有|owned?|already have)\s*([^，。,.!?]{1,50})", text, re.IGNORECASE)
        return [match.group(1).strip()] if match else []

    @staticmethod
    def _build_use_case(text: str, profile: Dict[str, Any]) -> str:
        parts = [str(profile.get("activity") or "").strip(), str(profile.get("location") or "").strip()]
        parts.extend(str(item) for item in profile.get("weather") or [])
        compact = " / ".join(part for part in parts if part)
        return compact or text[:160]
