from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ..utils.wine_entities import expand_wine_aliases, normalize_entity_text


_SKU_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*-)[A-Z]{2,}[A-Z0-9-]{4,}\b", re.IGNORECASE)
_MODEL_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_PRICE_UNDER_RE = re.compile(r"(?:under|below|<=?|低於|以下|不超過)\s*(?:nt\$?\s*)?([0-9,]+)", re.IGNORECASE)
_PRICE_OVER_RE = re.compile(r"(?:over|above|>=?|高於|以上|至少)\s*(?:nt\$?\s*)?([0-9,]+)", re.IGNORECASE)
_STOCK_MIN_RE = re.compile(r"(?:stock|inventory|庫存|可售|available|現貨)\D{0,12}([0-9]+)\s*(?:pcs|items|件|組|支|個)?", re.IGNORECASE)
_QUANTITY_MIN_RE = re.compile(r"(?:at least|至少|>=)\s*([0-9]+)\s*(?:pcs|items|件|組|支|個)?", re.IGNORECASE)
_SIZE_RE = re.compile(r"\b([0-9]+(?:\.[0-9]+)?)\s*(?:ml|l|cm|mm|m|inch|in|oz|lb|kg|g)\b", re.IGNORECASE)

_CATEGORY_TERMS = {
    "hiking": ("hiking", "trekking", "trail", "登山", "健行"),
    "fishing": ("fishing", "tackle", "rod", "reel", "釣具", "釣竿", "捲線器"),
    "camping": ("camping", "tent", "sleeping bag", "stove", "露營", "帳篷", "睡袋", "爐具"),
    "apparel": ("jacket", "shell", "pants", "gloves", "服飾", "外套", "手套"),
    "footwear": ("boot", "shoe", "sandal", "鞋", "登山鞋"),
    "accessory": ("headlamp", "lantern", "cooler", "accessory", "配件", "頭燈"),
}
_COLOR_TERMS = {
    "black": ("black", "黑"),
    "white": ("white", "白"),
    "gray": ("gray", "grey", "灰"),
    "blue": ("blue", "藍"),
    "green": ("green", "綠"),
    "orange": ("orange", "橘"),
    "yellow": ("yellow", "黃"),
    "red": ("red", "紅"),
}
_NEGATIVE_TERMS = {
    "sample": ("exclude sample", "not sample", "排除樣品", "不要樣品"),
    "used": ("exclude used", "not used", "排除二手", "不要二手"),
    "refurbished": ("exclude refurbished", "not refurbished", "排除整新品", "不要整新品"),
}


@dataclass
class CerpQueryPlan:
    raw_query: str
    search_keyword: str
    sku: Optional[str] = None
    vintage: Optional[int] = None
    region: Optional[str] = None
    color: Optional[str] = None
    bottle_size_ml: Optional[int] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    stock_min: Optional[int] = None
    require_sellable: bool = False
    include_unavailable: bool = False
    negative_filters: List[str] = field(default_factory=list)
    sort: Optional[str] = None
    normalized_aliases: List[str] = field(default_factory=list)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "search_keyword": self.search_keyword,
            "sku": self.sku,
            "vintage": self.vintage,
            "region": self.region,
            "color": self.color,
            "bottle_size_ml": self.bottle_size_ml,
            "price_min": self.price_min,
            "price_max": self.price_max,
            "stock_min": self.stock_min,
            "require_sellable": self.require_sellable,
            "include_unavailable": self.include_unavailable,
            "negative_filters": list(self.negative_filters),
            "sort": self.sort,
            "normalized_aliases": list(self.normalized_aliases),
            "planned_at": datetime.now(timezone.utc).isoformat(),
        }


class CerpQueryPlanner:
    """Internal natural-language planner layered on top of existing inventory APIs."""

    @classmethod
    def plan(cls, query: str) -> CerpQueryPlan:
        raw = str(query or "").strip()
        lowered = raw.lower()
        sku_match = _SKU_RE.search(raw)
        model_year_match = _MODEL_YEAR_RE.search(raw)
        size = cls._extract_size(raw)
        price_min = cls._extract_number(_PRICE_OVER_RE.search(raw))
        price_max = cls._extract_number(_PRICE_UNDER_RE.search(raw))
        stock_min = cls._extract_int(_STOCK_MIN_RE.search(raw)) or cls._extract_int(_QUANTITY_MIN_RE.search(raw))
        category = cls._match_term(lowered, _CATEGORY_TERMS)
        color = cls._match_term(lowered, _COLOR_TERMS)
        negative_filters = [
            key for key, terms in _NEGATIVE_TERMS.items()
            if any(term in lowered for term in terms)
        ]
        require_sellable = any(term in lowered for term in ("in stock", "currently in stock", "available", "現貨", "可售", "有庫存"))
        include_unavailable = any(term in lowered for term in ("unavailable", "reserved", "缺貨", "保留", "不可售"))
        sort = None
        if any(term in lowered for term in ("sorted by brand", "sorted by supplier", "按品牌", "依品牌")):
            sort = "brand_category"
        if any(term in lowered for term in ("top stock", "highest stock", "庫存最多", "最多庫存")):
            sort = "stock_desc"
        keyword = cls._build_keyword(raw, sku_match.group(0) if sku_match else None)
        aliases = expand_wine_aliases(keyword)
        return CerpQueryPlan(
            raw_query=raw,
            search_keyword=keyword,
            sku=sku_match.group(0).upper() if sku_match else None,
            vintage=int(model_year_match.group(0)) if model_year_match else None,
            region=category,
            color=color,
            bottle_size_ml=size,
            price_min=price_min,
            price_max=price_max,
            stock_min=stock_min if stock_min is not None else (1 if require_sellable else None),
            require_sellable=require_sellable,
            include_unavailable=include_unavailable,
            negative_filters=negative_filters,
            sort=sort,
            normalized_aliases=aliases,
        )

    @classmethod
    def post_filter(cls, products: Iterable[Dict[str, Any]], plan: CerpQueryPlan) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for product in products or []:
            if not isinstance(product, dict):
                continue
            if not cls._matches(product, plan):
                continue
            item = dict(product)
            item.setdefault("cerp_query_plan", plan.to_metadata())
            filtered.append(item)
        if plan.sort == "brand_category":
            filtered.sort(key=lambda item: (
                str(item.get("brand") or item.get("supplier") or item.get("producer") or "").lower(),
                str(item.get("category") or item.get("wine_class") or item.get("classification") or item.get("name") or "").lower(),
            ))
        elif plan.sort == "stock_desc":
            filtered.sort(key=lambda item: cls._number(item.get("stock") or item.get("stock_qty") or item.get("total_stock")), reverse=True)
        return filtered

    @classmethod
    def quote_criteria(cls, plan: CerpQueryPlan) -> Dict[str, Any]:
        criteria: Dict[str, Any] = {}
        if plan.vintage:
            criteria["vintage"] = plan.vintage
        if plan.color:
            criteria["color"] = plan.color
        if plan.region:
            criteria["region"] = plan.region.replace("_", " ")
        if plan.bottle_size_ml:
            criteria["bottle_size_ml"] = plan.bottle_size_ml
        if plan.price_min is not None:
            criteria["price_min"] = plan.price_min
        if plan.price_max is not None:
            criteria["price_max"] = plan.price_max
        if plan.stock_min is not None:
            criteria["stock_min"] = plan.stock_min
        return criteria

    @staticmethod
    def _matches(product: Dict[str, Any], plan: CerpQueryPlan) -> bool:
        searchable = " ".join(
            str(product.get(key) or "")
            for key in (
                "no",
                "id",
                "sku",
                "name",
                "name_en",
                "name_ch",
                "brand",
                "supplier",
                "producer",
                "category",
                "series",
                "model",
                "wine_class",
                "classification",
                "region",
                "appellation",
                "color",
            )
        )
        normalized = normalize_entity_text(searchable)
        if plan.sku and plan.sku.lower() not in searchable.lower():
            return False
        if plan.vintage and int(CerpQueryPlanner._number(product.get("model_year") or product.get("version_year") or product.get("vintage"))) != plan.vintage:
            return False
        if plan.color and plan.color not in normalize_entity_text(product.get("color") or product.get("wine_color") or searchable):
            return False
        if plan.region and not CerpQueryPlanner._category_matches(normalized, plan.region):
            return False
        if plan.bottle_size_ml and int(CerpQueryPlanner._number(product.get("capacity_ml") or product.get("bottle_size_ml") or product.get("size"))) != plan.bottle_size_ml:
            return False
        price = CerpQueryPlanner._number(product.get("price") or product.get("list_price"))
        if plan.price_min is not None and price < plan.price_min:
            return False
        if plan.price_max is not None and (price <= 0 or price > plan.price_max):
            return False
        stock = CerpQueryPlanner._number(product.get("stock") or product.get("stock_qty") or product.get("total_stock"))
        if plan.stock_min is not None and stock < plan.stock_min:
            return False
        if plan.require_sellable and stock <= 0:
            return False
        if "sample" in plan.negative_filters and "sample" in normalized:
            return False
        if "used" in plan.negative_filters and "used" in normalized:
            return False
        if "refurbished" in plan.negative_filters and "refurbished" in normalized:
            return False
        return True

    @staticmethod
    def _category_matches(normalized_text: str, category: str) -> bool:
        terms = _CATEGORY_TERMS.get(category, ())
        normalized_terms = [normalize_entity_text(term) for term in terms]
        return any(term and term in normalized_text for term in normalized_terms)

    @staticmethod
    def _extract_size(query: str) -> Optional[int]:
        match = _SIZE_RE.search(query)
        if not match:
            return None
        try:
            return int(float(match.group(1)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_number(match: Optional[re.Match[str]]) -> Optional[float]:
        if not match:
            return None
        return float(match.group(1).replace(",", ""))

    @staticmethod
    def _extract_int(match: Optional[re.Match[str]]) -> Optional[int]:
        value = CerpQueryPlanner._extract_number(match)
        return int(value) if value is not None else None

    @staticmethod
    def _number(value: Any) -> float:
        try:
            return float(str(value or "0").replace(",", ""))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _match_term(lowered: str, mapping: Dict[str, tuple[str, ...]]) -> Optional[str]:
        for key, terms in mapping.items():
            if any(term in lowered for term in terms):
                return key
        return None

    @staticmethod
    def _build_keyword(query: str, sku: Optional[str]) -> str:
        if sku:
            return sku
        subject = CerpQueryPlanner._extract_product_subject(query)
        if subject:
            return subject
        keyword = re.sub(
            r"\b(?:under|below|over|above|stock|inventory|currently|available|items?|pcs|retail|price|with|at least|sorted by|brand|supplier|category|then|model)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        keyword = re.sub(r"[<>=]|NT\$?|[0-9,]+", " ", keyword, flags=re.IGNORECASE)
        keyword = " ".join(keyword.split())
        return keyword or query

    @staticmethod
    def _extract_product_subject(query: str) -> str:
        text = str(query or "").strip()
        if not re.search(r"\b(?:stock|inventory|availability|available|retail|price|market context)\b", text, re.IGNORECASE):
            return ""
        patterns = (
            r"\bfor\s+(.+?)(?:\s+if\s+available\b|\s+and\s+how\b|\s+compared?\b|\?|$)",
            r"\b(?:price|stock|inventory|availability)\s+(?:for|of)\s+(.+?)(?:\s+if\s+available\b|\s+and\s+how\b|\s+compared?\b|\?|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            subject = match.group(1)
            subject = re.sub(r"\b(?:current|retail|price|stock|position|inventory|availability|available)\b", " ", subject, flags=re.IGNORECASE)
            subject = re.sub(r"[?.,;:]+", " ", subject)
            subject = " ".join(subject.split()).strip(" -")
            if subject:
                return subject
        return ""
