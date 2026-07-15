from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..cerp_service import CerpService


_CATEGORY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "rain_protection": (
        "rain jacket", "poncho", "pack cover", "dry bag", "waterproof", "rain protection",
        "雨衣", "雨具", "防水", "背包套", "防水袋",
    ),
    "shelter": ("tent", "shelter", "tarp", "canopy", "帳篷", "天幕"),
    "sleeping_gear": ("sleeping bag", "sleeping pad", "sleeping", "mat", "睡袋", "睡墊"),
    "lighting": ("headlamp", "lantern", "lighting", "lamp", "頭燈", "營燈", "照明"),
    "cooking_water": ("stove", "cookware", "water", "cooler", "爐具", "炊具", "飲水"),
    "storage_packs": ("backpack", "pack", "dry bag", "storage", "duffel", "背包", "收納", "防水袋"),
    "power": ("power", "solar", "battery", "充電", "電池", "太陽能"),
    "safety_repair": ("first aid", "safety", "repair", "emergency", "急救", "安全", "維修"),
    "fishing_gear": ("fishing", "rod", "reel", "lure", "hook", "line", "釣魚", "釣具"),
}

_ACTIVITY_TERMS: Dict[str, Tuple[str, ...]] = {
    "hiking": ("hiking", "trekking", "trail", "登山", "健行"),
    "camping": ("camping", "camp", "露營"),
    "fishing": ("fishing", "angling", "釣魚"),
    "outdoor": ("outdoor", "戶外"),
}

_HIKING_INCOMPATIBLE = (
    "tarp", "canopy", "camp furniture", "cooler", "stove", "cookware",
    "天幕", "露營家具", "冰桶", "爐具",
)

_CATEGORY_LABELS = {
    "zh": {
        "rain_protection": "防雨",
        "shelter": "遮蔽",
        "sleeping_gear": "睡眠保暖",
        "lighting": "照明",
        "cooking_water": "炊事與飲水",
        "storage_packs": "背負與乾燥收納",
        "power": "供電",
        "safety_repair": "安全與維修",
        "fishing_gear": "釣魚裝備",
    },
    "en": {
        "rain_protection": "rain protection",
        "shelter": "shelter",
        "sleeping_gear": "sleep and warmth",
        "lighting": "lighting",
        "cooking_water": "cooking and water",
        "storage_packs": "carrying and dry storage",
        "power": "power",
        "safety_repair": "safety and repair",
        "fishing_gear": "fishing gear",
    },
    "ja": {
        "rain_protection": "雨対策",
        "shelter": "シェルター",
        "sleeping_gear": "睡眠・保温",
        "lighting": "照明",
        "cooking_water": "調理・給水",
        "storage_packs": "携行・防水収納",
        "power": "電源",
        "safety_repair": "安全・補修",
        "fishing_gear": "釣り用品",
    },
}

_ACTIVITY_LABELS = {
    "zh": {"hiking": "登山", "camping": "露營", "fishing": "釣魚", "outdoor": "戶外"},
    "en": {"hiking": "hiking", "camping": "camping", "fishing": "fishing", "outdoor": "outdoor use"},
    "ja": {"hiking": "登山", "camping": "キャンプ", "fishing": "釣り", "outdoor": "アウトドア"},
}


@dataclass(frozen=True)
class ProductQueryPlan:
    search_terms: Tuple[str, ...]
    categories: Tuple[str, ...]
    required_features: Tuple[str, ...]
    excluded_features: Tuple[str, ...]
    preferred_brands: Tuple[str, ...]
    owned_gear: Tuple[str, ...]
    activity: Optional[str]
    location: Optional[str]
    duration: Optional[str]
    party_size: Optional[int]
    quantity: int
    weather: Tuple[str, ...]
    budget_min: Optional[float]
    budget_max: Optional[float]
    stock_min: int


class ProductBridgeService:
    """Plans and ranks only ERP-returned products using the saved need profile."""

    def __init__(self, cerp_service: Optional[CerpService] = None) -> None:
        self._cerp = cerp_service or CerpService()

    async def recommend(
        self,
        need_profile: Dict[str, Any],
        *,
        language: str = "zh-TW",
        limit: int = 6,
    ) -> Dict[str, Any]:
        source_timestamp = datetime.now(timezone.utc).isoformat()
        query_plan = self.build_query_plan(need_profile)
        raw_products = await self._fetch_candidates(query_plan)
        ranked = self._rank(raw_products, query_plan)
        selected = self._diversify(ranked, max(1, min(limit, 12)))
        product_results = [
            self._to_contract(product, matches, query_plan, source_timestamp, language)
            for _, product, matches in selected
        ]
        return {
            "product_results": product_results,
            "source_timestamp": source_timestamp,
            "text": self._answer_text(bool(product_results), language),
            "professional_guidance": self.professional_guidance(need_profile, language),
            "erp_status": "used" if product_results else "no_matches",
            "query_plan": {
                "search_terms": list(query_plan.search_terms),
                "categories": list(query_plan.categories),
                "required_features": list(query_plan.required_features),
                "activity": query_plan.activity,
                "location": query_plan.location,
                "duration": query_plan.duration,
                "party_size": query_plan.party_size,
                "quantity": query_plan.quantity,
                "weather": list(query_plan.weather),
                "stock_min": query_plan.stock_min,
            },
        }

    @classmethod
    def build_query_plan(cls, profile: Dict[str, Any]) -> ProductQueryPlan:
        categories = cls._unique(profile.get("categories") or [])
        required = cls._unique(profile.get("required_features") or [])
        weather = cls._unique(profile.get("weather") or [])
        activity = str(profile.get("activity") or "").strip() or None
        if any(item in {"rain", "humid", "wet"} for item in weather):
            required = cls._unique([*required, "waterproof"])
        terms: List[str] = []
        for category in categories:
            terms.extend(_CATEGORY_ALIASES.get(category, (category,))[:4])
        terms.extend(required)
        terms.extend(str(item) for item in profile.get("preferred_brands") or [])
        if activity and not categories:
            terms.extend(_ACTIVITY_TERMS.get(activity, (activity,))[:2])
        budget = profile.get("budget") if isinstance(profile.get("budget"), dict) else {}
        quantity = cls._integer(profile.get("quantity")) or 1
        party_size = cls._integer(profile.get("party_size"))
        duration = cls._duration_label(profile.get("duration"))
        if party_size and set(categories) & {"shelter", "sleeping_gear"}:
            terms.append(f"{party_size}P")
        if duration and cls._is_multi_day(duration):
            terms.extend(("compact", "durable"))
        return ProductQueryPlan(
            search_terms=tuple(cls._unique(terms)[:16]),
            categories=tuple(categories),
            required_features=tuple(required),
            excluded_features=tuple(cls._unique(profile.get("excluded_features") or [])),
            preferred_brands=tuple(cls._unique(profile.get("preferred_brands") or [])),
            owned_gear=tuple(cls._unique(profile.get("owned_gear") or [])),
            activity=activity,
            location=str(profile.get("location") or "").strip() or None,
            duration=duration,
            party_size=party_size,
            quantity=quantity,
            weather=tuple(weather),
            budget_min=cls._number(budget.get("min")),
            budget_max=cls._number(budget.get("max")),
            stock_min=quantity,
        )

    async def _fetch_candidates(self, plan: ProductQueryPlan) -> List[Dict[str, Any]]:
        calls = [self._cerp.fetch_top_stock_products(limit=100, allow_zero_stock=False)]
        search_products = getattr(self._cerp, "search_products", None)
        if callable(search_products):
            for term in plan.search_terms[:12]:
                calls.append(search_products(term, limit=30, page_size=50, raise_on_error=False))
        results = await asyncio.gather(*calls, return_exceptions=True)
        products: List[Dict[str, Any]] = []
        seen = set()
        for result in results:
            if isinstance(result, Exception):
                continue
            for product in result or []:
                if not isinstance(product, dict):
                    continue
                sku = self._sku(product)
                if not sku or sku.casefold() in seen:
                    continue
                seen.add(sku.casefold())
                products.append(product)
        return products

    def _rank(
        self,
        products: Sequence[Dict[str, Any]],
        plan: ProductQueryPlan,
    ) -> List[Tuple[float, Dict[str, Any], List[str]]]:
        ranked: List[Tuple[float, Dict[str, Any], List[str]]] = []
        preferred = {item.casefold() for item in plan.preferred_brands}
        for product in products:
            sku = self._sku(product)
            if not sku:
                continue
            brand = str(product.get("brand") or product.get("supplier") or product.get("invn006") or "").strip()
            haystack = self._product_haystack(product)
            if self._activity_incompatible(plan, haystack):
                continue
            if any(self._excluded_match(item, brand, haystack) for item in plan.excluded_features):
                continue
            if any(item.casefold() in haystack for item in plan.owned_gear):
                continue

            price = self._number(product.get("price") if product.get("price") is not None else product.get("list_price"))
            if plan.budget_max is not None and price is not None and price > plan.budget_max:
                continue
            if plan.budget_min is not None and price is not None and price < plan.budget_min:
                continue
            stock = self._number(product.get("stock") if product.get("stock") is not None else product.get("stock_qty")) or 0.0
            if stock < plan.stock_min:
                continue

            score = 0.0
            matches: List[str] = []
            category_hits = []
            for category in plan.categories:
                aliases = _CATEGORY_ALIASES.get(category, (category,))
                if any(alias.casefold() in haystack for alias in aliases):
                    category_hits.append(category)
                    score += 6.0
                    matches.append(f"category:{category}")
            if plan.categories and not category_hits:
                continue

            for feature in plan.required_features:
                if feature.casefold() in haystack or self._feature_alias_match(feature, haystack):
                    score += 2.5
                    matches.append(f"feature:{feature}")
            if plan.required_features and not category_hits and not any(item.startswith("feature:") for item in matches):
                continue
            if plan.activity:
                score += 1.5
                matches.append(f"activity:{plan.activity}")
            capacity = self._capacity(product)
            if plan.party_size and capacity is not None and set(plan.categories) & {"shelter", "sleeping_gear"}:
                if capacity < plan.party_size:
                    continue
                score += 1.5
                matches.append("party_size")
            if plan.duration and self._is_multi_day(plan.duration) and any(
                term in haystack for term in ("compact", "durable", "storage", "power", "pack", "收納", "耐用")
            ):
                score += 1.0
                matches.append("multi_day")
            if any(item in {"rain", "humid", "wet"} for item in plan.weather) and (
                "waterproof" in haystack or "rain" in haystack or "防水" in haystack
            ):
                score += 2.0
                matches.append("weather:rain")
            if brand and brand.casefold() in preferred:
                score += 3.0
                matches.append(f"brand:{brand}")
            if stock > 0:
                score += min(stock / 100.0, 1.0)
                matches.append("in_stock")
            if plan.budget_max is not None and price is not None:
                matches.append("within_budget")

            meaningful = [item for item in matches if item.startswith(("category:", "feature:", "weather:", "brand:"))]
            if not meaningful:
                continue
            ranked.append((score, product, list(dict.fromkeys(matches))))
        ranked.sort(key=lambda row: (-row[0], self._sku(row[1])))
        return ranked

    @staticmethod
    def _diversify(
        ranked: Sequence[Tuple[float, Dict[str, Any], List[str]]],
        limit: int,
    ) -> List[Tuple[float, Dict[str, Any], List[str]]]:
        selected: List[Tuple[float, Dict[str, Any], List[str]]] = []
        category_counts: Dict[str, int] = {}
        for row in ranked:
            category = str(row[1].get("category") or row[1].get("type") or "uncategorized").casefold()
            if category_counts.get(category, 0) >= 2:
                continue
            selected.append(row)
            category_counts[category] = category_counts.get(category, 0) + 1
            if len(selected) >= limit:
                return selected
        selected_ids = {ProductBridgeService._sku(item[1]) for item in selected}
        for row in ranked:
            if ProductBridgeService._sku(row[1]) in selected_ids:
                continue
            selected.append(row)
            if len(selected) >= limit:
                break
        return selected

    @classmethod
    def _to_contract(
        cls,
        product: Dict[str, Any],
        matches: Sequence[str],
        plan: ProductQueryPlan,
        timestamp: str,
        language: str,
    ) -> Dict[str, Any]:
        matched = list(dict.fromkeys(str(item) for item in matches if item))
        return {
            "sku": cls._sku(product),
            "name": str(product.get("name") or product.get("product_name") or product.get("name_ch") or product.get("name_en") or product.get("invn005") or ""),
            "brand": str(product.get("brand") or product.get("supplier") or product.get("invn006") or ""),
            "category": str(product.get("category") or product.get("type") or product.get("invn802") or product.get("invn030") or ""),
            "specification": cls._specification(product),
            "price": product.get("price") if product.get("price") is not None else product.get("list_price"),
            "stock": product.get("stock") if product.get("stock") is not None else product.get("stock_qty"),
            "recommendation_reason": cls._recommendation_reason(product, matched, plan, language),
            "matched_requirements": matched,
            "source_timestamp": timestamp,
        }

    @classmethod
    def _recommendation_reason(
        cls,
        product: Dict[str, Any],
        matches: Sequence[str],
        plan: ProductQueryPlan,
        language: str,
    ) -> str:
        locale = cls._locale(language)
        category_labels = _CATEGORY_LABELS[locale]
        activity_labels = _ACTIVITY_LABELS[locale]
        categories = [
            category_labels.get(item.split(":", 1)[1], item.split(":", 1)[1])
            for item in matches
            if item.startswith("category:")
        ][:2]
        activity = activity_labels.get(plan.activity or "", "")
        wet = any(item in {"rain", "humid", "wet"} for item in plan.weather)
        in_stock = "in_stock" in matches
        within_budget = "within_budget" in matches
        specification = cls._specification(product)
        if locale == "en":
            context = ", ".join(item for item in (plan.duration, plan.location, "wet-weather" if wet else "", activity) if item)
            lead = f"Suitable for {context}: " if context else "Recommended because it "
            needs = f"matches {', '.join(categories)} needs" if categories else "matches the requested product features"
            facts = [f"ERP specification: {specification}" if specification else "", "currently in stock" if in_stock else "", "within budget" if within_budget else ""]
            return lead + needs + ("; " + ", ".join(item for item in facts if item) if any(facts) else "") + "."
        if locale == "ja":
            context = "・".join(item for item in (plan.duration, plan.location, "雨天" if wet else "", activity) if item)
            lead = f"{context}向け：" if context else "おすすめ理由："
            needs = "・".join(categories) + "の条件に合致" if categories else "指定された商品条件に合致"
            facts = [f"ERP仕様は{specification}" if specification else "", "在庫あり" if in_stock else "", "予算内" if within_budget else ""]
            return lead + needs + ("、" + "・".join(item for item in facts if item) if any(facts) else "") + "。"
        context = "、".join(item for item in (plan.duration, plan.location, "雨天" if wet else "", activity) if item)
        lead = f"適合{context}使用：" if context else "推薦原因："
        needs = f"符合{'與'.join(categories)}需求" if categories else "符合指定的商品條件"
        facts = [f"ERP 規格為 {specification}" if specification else "", "目前有庫存" if in_stock else "", "在預算內" if within_budget else ""]
        return lead + needs + ("，" + "，且".join(item for item in facts if item) if any(facts) else "") + "。"

    @staticmethod
    def _answer_text(has_results: bool, language: str) -> str:
        locale = ProductBridgeService._locale(language)
        if has_results:
            return {
                "zh": "以下商品來自 ERP，並已依目前需求、規格、預算與庫存條件排序。",
                "en": "These ERP products are ranked by the current needs, specifications, budget, and stock.",
                "ja": "以下は、現在の要件・仕様・予算・在庫条件に基づいて順位付けしたERP商品です。",
            }[locale]
        return {
            "zh": "ERP 目前沒有符合全部條件的商品；以下僅提供通用選擇原則，不會以低相關商品補足。",
            "en": "ERP currently has no products matching all requirements. Only general selection guidance is provided.",
            "ja": "ERPには現在、すべての条件に合う商品がありません。一般的な選定基準のみ案内します。",
        }[locale]

    @staticmethod
    def professional_guidance(profile: Dict[str, Any], language: str) -> str:
        weather = {str(item) for item in profile.get("weather") or []}
        locale = ProductBridgeService._locale(language)
        wet = bool(weather & {"rain", "humid", "wet"})
        if locale == "en":
            advice = "For wet conditions, prioritize layered rain protection, dry storage, traction, and a conservative turnaround plan." if wet else "Confirm fit, expected conditions, emergency margins, and total carried weight before purchasing."
            return f"Professional guidance: {advice}"
        if locale == "ja":
            advice = "雨天では、防雨レイヤー、防水収納、グリップ、安全な撤退基準を優先してください。" if wet else "購入前に適合性、想定条件、緊急時の余裕、総重量を確認してください。"
            return f"専門的な提案：{advice}"
        advice = "雨天應優先考量分層防雨、乾燥收納、防滑與保守撤退計畫。" if wet else "購買前請確認適用情境、尺寸、緊急備援與總攜行重量。"
        return f"專業建議：{advice}"

    @staticmethod
    def _activity_incompatible(plan: ProductQueryPlan, haystack: str) -> bool:
        if plan.activity != "hiking":
            return False
        explicitly_requested = set(plan.categories) & {"shelter", "sleeping_gear", "cooking_water"}
        return not explicitly_requested and any(term.casefold() in haystack for term in _HIKING_INCOMPATIBLE)

    @staticmethod
    def _feature_alias_match(feature: str, haystack: str) -> bool:
        aliases = {
            "waterproof": ("waterproof", "rain", "dry", "防水", "雨"),
            "lightweight": ("lightweight", "ultralight", "輕量"),
            "compact": ("compact", "packable", "收納", "輕巧"),
            "warm": ("warm", "insulated", "down", "保暖", "羽絨"),
        }
        return any(item.casefold() in haystack for item in aliases.get(feature.casefold(), (feature,)))

    @staticmethod
    def _excluded_match(value: str, brand: str, haystack: str) -> bool:
        normalized = str(value or "").strip()
        if not normalized:
            return False
        if normalized.casefold().startswith("brand:"):
            return brand.casefold() == normalized.split(":", 1)[1].strip().casefold()
        return normalized.casefold() in haystack

    @staticmethod
    def _product_haystack(product: Dict[str, Any]) -> str:
        keys = (
            "name", "product_name", "name_ch", "name_en", "invn005", "brand", "supplier",
            "category", "type", "invn802", "invn030", "specification", "spec", "spec1",
            "model", "model_name", "model_year", "invn807", "invn051", "material", "size",
        )
        return " ".join(str(product.get(key) or "") for key in keys).casefold()

    @staticmethod
    def _specification(product: Dict[str, Any]) -> str:
        for key in ("specification", "spec", "spec1", "model", "model_name", "model_year", "invn807", "invn051", "size"):
            value = str(product.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _sku(product: Dict[str, Any]) -> str:
        return str(product.get("no") or product.get("sku") or product.get("code") or product.get("id") or product.get("invn002") or "").strip()

    @staticmethod
    def _number(value: Any) -> Optional[float]:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value: Any) -> Optional[int]:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _capacity(product: Dict[str, Any]) -> Optional[int]:
        import re

        text = " ".join(
            str(product.get(key) or "")
            for key in ("specification", "spec", "spec1", "model", "model_year", "invn807", "invn051", "size")
        )
        match = re.search(r"\b(\d{1,2})\s*P\b", text, re.IGNORECASE)
        return int(match.group(1)) if match else None

    @staticmethod
    def _is_multi_day(value: str) -> bool:
        import re

        text = str(value or "")
        if re.search(r"過夜|多日|overnight|multi[- ]?day", text, re.IGNORECASE):
            return True
        match = re.search(r"(\d+)\s*(?:天|days?)", text, re.IGNORECASE)
        return bool(match and int(match.group(1)) >= 2)

    @staticmethod
    def _duration_label(value: Any) -> Optional[str]:
        if isinstance(value, dict):
            amount = value.get("value")
            unit = str(value.get("unit") or "").strip()
            if amount not in (None, ""):
                return f"{amount}{unit}"
            return None
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _unique(values: Sequence[Any]) -> List[str]:
        output: List[str] = []
        seen = set()
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized.casefold() not in seen:
                output.append(normalized)
                seen.add(normalized.casefold())
        return output

    @staticmethod
    def _locale(language: str) -> str:
        normalized = str(language or "").lower()
        if normalized.startswith("en"):
            return "en"
        if normalized.startswith("ja"):
            return "ja"
        return "zh"
