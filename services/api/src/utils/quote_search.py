from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

_VINTAGE_RE = re.compile(r"(19\d{2}|20\d{2})")
_QUANTITY_RE = re.compile(
    r"\b\d+\s*(?:\u74f6|\u652f|\u7bb1|\u7d44|\u6b3e|wine|wines|bottle|bottles|case|cases|pack|packs)\b",
    flags=re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")
_NORMALIZE_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff~]+", re.IGNORECASE)
_PRICE_NUMBER_RE = r"(?:\d{1,3}(?:,\d{3})+|\d{3,5})"
_PRICE_RANGE_PATTERN = re.compile(
    rf"(?:(?:vip|vip\s*price|價格|價位|售價|預算|報價|price|priced?)\D{{0,8}})?"
    rf"({_PRICE_NUMBER_RE})\s*(?:~|～|-|至|到|between)\s*({_PRICE_NUMBER_RE})",
    flags=re.IGNORECASE,
)
_PRICE_MAX_PATTERN = re.compile(
    rf"(?:(?:vip|vip\s*price|價格|價位|售價|預算|報價|price|priced?)\D{{0,8}})?"
    rf"(?:(?:under|below|less than|up to|不超過|不到|低於|小於)\s*\$?\s*({_PRICE_NUMBER_RE})|"
    rf"\$?\s*({_PRICE_NUMBER_RE})\s*(?:以下|以內))",
    flags=re.IGNORECASE,
)
_PRICE_MIN_PATTERN = re.compile(
    rf"(?:(?:vip|vip\s*price|價格|價位|售價|預算|報價|price|priced?)\D{{0,8}})?"
    rf"(?:(?:above|over|more than|at least|不低於|高於|大於)\s*\$?\s*({_PRICE_NUMBER_RE})|"
    rf"\$?\s*({_PRICE_NUMBER_RE})\s*(?:以上))",
    flags=re.IGNORECASE,
)
_PRICE_CONTEXT_RE = re.compile(r"(?:vip|vip\s*價|vip\s*price|價格|價位|售價|預算|報價|price|priced?)", re.IGNORECASE)
_VIP_SCOPE_RE = re.compile(r"(?:vip|vip\s*價|vip\s*price)", re.IGNORECASE)
_BLANC_DE_BLANCS_RE = re.compile(r"\bblanc\s+de\s+blancs\b|白中白", re.IGNORECASE)
_CREMANT_RE = re.compile(r"\bcr[eé]mant\b|氣泡酒", re.IGNORECASE)
_STILL_WINE_CONTEXT_RE = re.compile(r"(?:紅酒|白酒|粉紅酒|橘酒|red wine|white wine|rose wine|orange wine)", re.IGNORECASE)

_PRICE_CONTEXT_TERMS = r"vip|vip\s*價|vip\s*價格|vip\s*price|價格|價位|售價|預算|報價|price|priced?"
_PRICE_RANGE_PATTERN = re.compile(
    rf"(?:(?:{_PRICE_CONTEXT_TERMS})\D{{0,8}})?"
    rf"({_PRICE_NUMBER_RE})\s*(?:~|-|到|至|between)\s*({_PRICE_NUMBER_RE})",
    flags=re.IGNORECASE,
)
_PRICE_MAX_PATTERN = re.compile(
    rf"(?:(?:{_PRICE_CONTEXT_TERMS})\D{{0,8}})?"
    rf"(?:(?:under|below|less than|up to|以內|以下|低於|不超過|小於)\s*(?:nt\$?\s*)?\$?\s*({_PRICE_NUMBER_RE})|"
    rf"(?:nt\$?\s*)?\$?\s*({_PRICE_NUMBER_RE})\s*(?:以內|以下|內|以下的|以內的))",
    flags=re.IGNORECASE,
)
_PRICE_MIN_PATTERN = re.compile(
    rf"(?:(?:{_PRICE_CONTEXT_TERMS})\D{{0,8}})?"
    rf"(?:(?:above|over|more than|at least|以上|高於|超過|大於)\s*(?:nt\$?\s*)?\$?\s*({_PRICE_NUMBER_RE})|"
    rf"(?:nt\$?\s*)?\$?\s*({_PRICE_NUMBER_RE})\s*(?:以上|起))",
    flags=re.IGNORECASE,
)
_PRICE_CONTEXT_RE = re.compile(rf"(?:{_PRICE_CONTEXT_TERMS})", re.IGNORECASE)
_VIP_SCOPE_RE = re.compile(r"(?:vip|vip\s*價|vip\s*價格|vip\s*price)", re.IGNORECASE)

_COLOR_PATTERNS = (
    ("rose", (r"\u7c89\u7d05\u9152", r"\u6843\u7d05\u9152", r"ros[eé]", r"\brose\b", r"\bpink wine\b", r"\bpink\b")),
    ("orange", (r"\u6a58\u9152", r"\borange wine\b", r"\borange\b")),
    ("white", (r"\u767d\u9152", r"\bwhite wine\b", r"\bwhite\b", r"\bblanc\b")),
    ("red", (r"\u7d05\u9152", r"\bred wine\b", r"\bred\b", r"\brouge\b")),
)

_STYLE_PATTERNS = (
    (
        "sparkling",
        (
            r"\u6c23\u6ce1\u9152",
            r"\u6c23\u6ce1",
            r"\u8d77\u6ce1\u9152",
            r"\u8d77\u6ce1",
            r"\u9999\u6ab3",
            r"\u9999\u69df",
            r"\bchampagne\b",
            r"\bsparkling\b",
            r"\bpet[\s-]?nat\b",
            r"\bbubbly\b",
            r"\bprosecco\b",
            r"\bcava\b",
            r"\bmousseux\b",
        ),
    ),
    ("still", (r"\u975c\u614b\u9152", r"\u975c\u614b", r"still wine", r"\bstill\b")),
)

_REGION_PATTERNS = (
    ("champagne", (r"\u9999\u6ab3", r"\u9999\u69df", r"\bchampagne\b")),
    ("burgundy", (r"\u52c3\u6839\u5730", r"\u5e03\u6839\u5730", r"\u52c3\u826e\u7b2c", r"\bburgundy\b", r"\bbourgogne\b")),
    ("bordeaux", (r"\u6ce2\u723e\u591a", r"\bbordeaux\b")),
    ("loire", (r"\u7f85\u4e9e\u723e", r"\bloire\b")),
    ("rhone", (r"\u9686\u6cb3", r"\u7f85\u8a25", r"\brhone\b", r"\brh[oô]ne\b")),
    ("napa", (r"\u7d0d\u5e15", r"\bnapa\b")),
    ("rioja", (r"\u91cc\u5967\u54c8", r"\brioja\b")),
    ("tuscany", (r"\u6258\u65af\u5361\u5c3c", r"\btuscany\b", r"\btoscana\b")),
)

_REGION_CANONICAL_LABELS = {
    "champagne": "Champagne",
    "burgundy": "Burgundy",
    "bordeaux": "Bordeaux",
    "loire": "Loire",
    "rhone": "Rhone",
    "napa": "Napa",
    "rioja": "Rioja",
    "tuscany": "Tuscany",
}

_INTENT_PATTERNS = (
    r"\u5831\u50f9\u6e05\u55ae",
    r"\u5831\u50f9\u55ae",
    r"\u5831\u50f9",
    r"\u9152\u6b3e",
    r"\u63a8\u85a6",
    r"\u5efa\u8b70",
    r"\u6e05\u55ae",
    r"\u5eab\u5b58",
    r"\u5b58\u8ca8",
    r"\u73fe\u8ca8",
    r"\u6709\u8ca8",
    r"\u627e",
    r"\u60f3\u8981",
    r"\u8acb",
    r"\u5217\u51fa",
    r"\u53ea\u5217\u51fa",
    r"\u67e5\u8a62",
    r"\u641c\u5c0b",
    r"quote",
    r"quotation",
    r"stock",
    r"inventory",
    r"list",
)

_USER_COLOR_TO_QUERY = {
    "red": "red wine",
    "white": "white wine",
    "rose": "rose wine",
    "orange": "orange wine",
}

_PRODUCT_COLOR_ALIASES = {
    "red": "red",
    "white": "white",
    "while": "white",
    "rose": "rose",
    "rosé": "rose",
    "pink": "rose",
    "orange": "orange",
    "other": "other",
}

_HARD_CRITERIA_KEYS = (
    "producer",
    "wine_name",
    "region",
    "region_filter",
    "vintage",
    "color",
    "style",
    "classification",
    "price_min",
    "price_max",
    "price_scope",
)
_SOFT_CRITERIA_KEYS = ("grape", "village", "vineyard")
_QUOTE_ENTITY_PREFIXES = {"ys", "chateau", "clos", "maison", "champagne"}
_IDENTITY_GENERIC_TOKENS = {
    "bottle",
    "bottles",
    "case",
    "cases",
    "inventory",
    "list",
    "quote",
    "red",
    "rose",
    "sparkling",
    "still",
    "stock",
    "white",
    "wine",
    "wines",
}


def _coerce_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _coerce_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = [_coerce_text(item) for item in value]
        return [item for item in values if item]
    text = _coerce_text(value)
    return [text] if text else []


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    deaccented = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    normalized = _NORMALIZE_RE.sub("", deaccented.casefold())
    return normalized.strip()


def normalize_quote_input_text(value: Any) -> str:
    text = _coerce_text(value) or ""
    if not text:
        return ""
    cleaned_chars: List[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith("C"):
            cleaned_chars.append(" ")
            continue
        if category == "Co":
            cleaned_chars.append(" ")
            continue
        cleaned_chars.append(char)
    cleaned = "".join(cleaned_chars)
    cleaned = re.sub(r"[\uE000-\uF8FF]+", " ", cleaned)
    cleaned = re.sub(r"[^\w\s\u4e00-\u9fff&'./,\-~]+", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;:/-")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def is_low_readability_quote_query(value: Any) -> bool:
    text = _coerce_text(value) or ""
    if not text:
        return True
    normalized = normalize_quote_input_text(text)
    if not normalized:
        return True
    latin_tokens = re.findall(r"[A-Za-z0-9]{2,}", normalized)
    han_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
    readable_units = len(latin_tokens) + len(han_chars)
    if readable_units == 0:
        return True
    replacement_chars = text.count("�")
    suspicious_marks = len(re.findall(r"\?{2,}|�{1,}", text))
    if replacement_chars >= 1 or suspicious_marks >= 2:
        return True
    if len(normalized) <= 3 and readable_units <= 1:
        return True
    return False


def _meaningful_query_tokens(text: str) -> List[str]:
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(char)
    )
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.casefold())
        if len(token) > 1
    ]


def _alias_value_supported_by_query(text: str, candidate: Any) -> bool:
    value = _coerce_text(candidate)
    if not value:
        return False
    query_tokens = set(_meaningful_query_tokens(text))
    candidate_tokens = set(_meaningful_query_tokens(value))
    if not candidate_tokens:
        return False
    return candidate_tokens.issubset(query_tokens)


def _finalize_alias_filter_values(values: Iterable[str]) -> Any:
    deduped = _dedupe_pieces([item for item in values if _coerce_text(item)])
    if not deduped:
        return None
    return deduped if len(deduped) > 1 else deduped[0]


def _canonical_region_label(value: str) -> str:
    return _REGION_CANONICAL_LABELS.get(value, value.title())


def _normalize_region_filter_value(value: Any) -> Optional[str]:
    text = _coerce_text(value)
    if not text:
        return None
    if re.search(r"[,/|>]+", text):
        text = re.split(r"[,/|>]+", text, maxsplit=1)[0].strip(" -")
        if not text:
            return None
    detected = _detect_mapped_value(text, _REGION_PATTERNS)
    if detected:
        return _canonical_region_label(detected)
    return text or None


def _derive_quote_region_filter(text: str, *fallbacks: Any) -> Optional[str]:
    detected = _detect_mapped_value(text or "", _REGION_PATTERNS)
    if detected:
        return _canonical_region_label(detected)
    for fallback in fallbacks:
        normalized = _normalize_region_filter_value(fallback)
        if normalized:
            return normalized
    return None


def _merge_region_contexts(region_filter: Optional[str], *groups: Any) -> List[str]:
    normalized_groups: List[str] = []
    for group in groups:
        for item in _coerce_text_list(group):
            if re.search(r"[,/|>]+", item):
                normalized_groups.append(item)
                continue
            detected = _detect_mapped_value(item, _REGION_PATTERNS)
            normalized_groups.append(_canonical_region_label(detected) if detected else item)
    merged = _merge_profile_values(normalized_groups)
    if not region_filter:
        return merged
    filtered = [value for value in merged if value.casefold() != region_filter.casefold()]
    return filtered or [region_filter]


def sanitize_quote_alias_filters(text: str, alias_filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(alias_filters, dict):
        return {}

    normalized_text = normalize_quote_input_text(text)
    sanitized: Dict[str, Any] = {}

    producer_values = [
        item
        for item in _coerce_text_list(alias_filters.get("producer"))
        if _alias_value_supported_by_query(normalized_text, item)
    ]
    producer_value = _finalize_alias_filter_values(producer_values)
    if producer_value:
        sanitized["producer"] = producer_value

    query_region = _derive_quote_region_filter(normalized_text)
    alias_region = _normalize_region_filter_value(_extract_alias_filter_value(alias_filters, "region", "invn030"))
    if query_region:
        sanitized["region"] = query_region
    elif alias_region and _alias_value_supported_by_query(normalized_text, alias_region):
        sanitized["region"] = alias_region

    style = normalize_quote_style(normalized_text) or normalize_quote_style(
        _extract_alias_filter_value(alias_filters, "style")
    )
    if style:
        sanitized["style"] = style

    classification_values = [
        item
        for item in _coerce_text_list(alias_filters.get("classification"))
        if _alias_value_supported_by_query(normalized_text, item)
    ]
    classification_value = _finalize_alias_filter_values(classification_values)
    if classification_value:
        sanitized["classification"] = classification_value

    grape_candidates = _coerce_text_list(alias_filters.get("grape_varieties")) + _coerce_text_list(
        alias_filters.get("grape")
    )
    grape_values = [
        item
        for item in grape_candidates
        if _alias_value_supported_by_query(normalized_text, item)
    ]
    grape_value = _finalize_alias_filter_values(grape_values)
    if grape_value:
        sanitized["grape"] = grape_value

    return sanitized


def sanitize_quote_alias_filters_for_cerp(text: str, alias_filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    clean_alias_filters = sanitize_quote_alias_filters(text, alias_filters)
    producer = clean_alias_filters.get("producer")
    if not producer:
        return {}
    return {"producer": producer}


def _infer_quote_named_entities(text: str) -> tuple[Optional[str], Optional[str]]:
    cleaned = normalize_quote_input_text(text)
    if not cleaned:
        return None, None
    without_vintage = _VINTAGE_RE.sub(" ", cleaned)
    without_vintage = _strip_intent_terms(without_vintage)
    tokens = re.findall(r"[A-Za-z][A-Za-z'&.\-]*", without_vintage)
    if len(tokens) < 4:
        return None, None
    producer_len = 3 if tokens[0].casefold() in _QUOTE_ENTITY_PREFIXES and len(tokens) >= 5 else 2
    producer_tokens = tokens[:producer_len]
    wine_tokens = tokens[producer_len:]
    if not producer_tokens or not wine_tokens:
        return None, None
    producer = " ".join(producer_tokens).strip()
    wine_name = " ".join(wine_tokens).strip()
    return (producer or None), (wine_name or None)


def limit_quote_query_variants(variants: Iterable[Any], max_items: int = 3) -> List[str]:
    limited: List[str] = []
    for item in variants:
        value = normalize_quote_input_text(item)
        if not value:
            continue
        if value.casefold() in {existing.casefold() for existing in limited}:
            continue
        limited.append(value)
        if len(limited) >= max_items:
            break
    return limited


def _contains_pattern(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _detect_mapped_value(text: str, definitions: Iterable[tuple[str, Iterable[str]]]) -> Optional[str]:
    lowered = (text or "").casefold()
    for canonical, patterns in definitions:
        if _contains_pattern(lowered, patterns):
            return canonical
    return None


def normalize_quote_color(value: Any) -> Optional[str]:
    text = _coerce_text(value)
    if not text:
        return None
    mapped = _PRODUCT_COLOR_ALIASES.get(text.casefold())
    if mapped:
        return mapped
    return _detect_mapped_value(text, _COLOR_PATTERNS)


def normalize_quote_style(value: Any) -> Optional[str]:
    text = _coerce_text(value)
    if not text:
        return None
    return _detect_mapped_value(text, _STYLE_PATTERNS)


def _parse_price_number(value: Any) -> Optional[float]:
    text = _coerce_text(value)
    if not text:
        return None
    cleaned = text.replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _price_scope_from_text(text: str, fallback: Optional[str] = None) -> Optional[str]:
    normalized_fallback = _coerce_text(fallback)
    if normalized_fallback:
        token = normalized_fallback.strip().lower()
        if token in {"vip", "list"}:
            return token
    raw = str(text or "")
    if raw and _VIP_SCOPE_RE.search(raw):
        return "vip"
    return normalized_fallback or "list"


def _strip_price_mentions(text: str) -> str:
    cleaned = str(text or "")
    for pattern in (_PRICE_RANGE_PATTERN, _PRICE_MAX_PATTERN, _PRICE_MIN_PATTERN):
        cleaned = pattern.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _extract_price_constraints(text: str, fallback_scope: Optional[str] = None) -> Dict[str, Any]:
    raw = str(text or "")
    scope = _price_scope_from_text(raw, fallback_scope)
    range_match = _PRICE_RANGE_PATTERN.search(raw)
    if range_match and _PRICE_CONTEXT_RE.search(raw):
        low = _parse_price_number(range_match.group(1))
        high = _parse_price_number(range_match.group(2))
        if low is not None and high is not None:
            lower, upper = sorted((low, high))
            return {"price_min": lower, "price_max": upper, "price_scope": scope}
    max_match = _PRICE_MAX_PATTERN.search(raw)
    if max_match:
        maximum = _parse_price_number(max_match.group(1) or max_match.group(2))
        if maximum is not None:
            return {"price_min": None, "price_max": maximum, "price_scope": scope}
    min_match = _PRICE_MIN_PATTERN.search(raw)
    if min_match:
        minimum = _parse_price_number(min_match.group(1) or min_match.group(2))
        if minimum is not None:
            return {"price_min": minimum, "price_max": None, "price_scope": scope}
    return {}


def _extract_vintage(text: str, fallback: Optional[str] = None) -> Optional[str]:
    match = _VINTAGE_RE.search(_strip_price_mentions(text))
    if match:
        return match.group(1)
    return _coerce_text(fallback)


def _extract_region(text: str, fallback: Optional[str] = None) -> Optional[str]:
    detected = _detect_mapped_value(text, _REGION_PATTERNS)
    if detected:
        return detected
    return _coerce_text(fallback)


def _strip_intent_terms(text: str) -> str:
    cleaned = _QUANTITY_RE.sub(" ", text or "")
    cleaned = _strip_price_mentions(cleaned)
    if _INTENT_PATTERNS:
        cleaned = re.sub("|".join(_INTENT_PATTERNS), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\u7684\u8981\u8acb\u60f3\u627e\u518d\u628a\u7d66\u6211\u5e6b\u6211]+", " ", cleaned)
    cleaned = re.sub(r"[，,。.!?？/]+", " ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _infer_default_still_style(text: str, color: Optional[str], explicit_style: Optional[str]) -> Optional[str]:
    if explicit_style or not color:
        return explicit_style
    raw = str(text or "")
    if not raw or not _STILL_WINE_CONTEXT_RE.search(raw):
        return explicit_style
    if normalize_quote_style(raw):
        return explicit_style
    return "still"


def _infer_classification(text: str, fallback: Optional[str] = None) -> Optional[str]:
    raw = str(text or "")
    if _BLANC_DE_BLANCS_RE.search(raw):
        return "Blanc de Blancs"
    return _coerce_text(fallback)


def _identity_tokens(value: Any) -> List[str]:
    text = _coerce_text(value)
    if not text:
        return []
    text = _strip_intent_terms(text)
    text = "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    tokens = []
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        if len(token) <= 1:
            continue
        if token in _IDENTITY_GENERIC_TOKENS:
            continue
        tokens.append(token)
    return tokens


def _criteria_identity_queries(criteria: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("raw_query", "canonical_query", "resolved_query", "keywords"):
        text = _coerce_text(criteria.get(key))
        if text:
            values.append(text)
    for item in criteria.get("query_variants") or []:
        text = _coerce_text(item)
        if text:
            values.append(text)
    alias_filters = criteria.get("alias_filters")
    if isinstance(alias_filters, dict):
        for value in alias_filters.values():
            values.extend(_coerce_text_list(value))
    return _dedupe_pieces(values)


def quote_product_identity_score(product: Dict[str, Any], criteria: Optional[Dict[str, Any]]) -> float:
    if not isinstance(criteria, dict):
        return 0.0
    product_tokens = set(_identity_tokens(_build_product_text(product)))
    if not product_tokens:
        return 0.0
    best = 0.0
    for query in _criteria_identity_queries(criteria):
        query_tokens = _identity_tokens(query)
        alpha_tokens = [token for token in query_tokens if not token.isdigit()]
        if len(query_tokens) < 4 or len(alpha_tokens) < 3:
            continue
        overlap = set(query_tokens) & product_tokens
        if len(overlap) < 4:
            continue
        coverage = len(overlap) / len(set(query_tokens))
        if coverage >= 0.8:
            best = max(best, 8.0 + (coverage * 4.0))
    return best


def _dedupe_pieces(pieces: Iterable[str]) -> List[str]:
    ordered: List[str] = []
    seen: set[str] = set()
    for piece in pieces:
        value = piece.strip()
        if not value:
            continue
        token = value.casefold()
        if token in seen:
            continue
        seen.add(token)
        ordered.append(value)
    return ordered


def _first_nonempty(*values: Any) -> Optional[str]:
    for value in values:
        text = _coerce_text(value)
        if text:
            return text
    return None


def _extract_alias_filter_value(alias_filters: Optional[Dict[str, Any]], *keys: str) -> Optional[str]:
    if not isinstance(alias_filters, dict):
        return None
    for key in keys:
        values = _coerce_text_list(alias_filters.get(key))
        if values:
            return values[0]
    return None


def _normalize_hit_meta(hit: Any) -> Dict[str, Any]:
    if not isinstance(hit, dict):
        return {}
    meta = hit.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return meta if isinstance(meta, dict) else {}


def _extract_knowledge_value(knowledge_hits: Optional[List[Dict[str, Any]]], *keys: str) -> Optional[str]:
    values: List[str] = []
    for hit in knowledge_hits or []:
        meta = _normalize_hit_meta(hit)
        for key in keys:
            values.extend(_coerce_text_list(meta.get(key)))
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def _extract_knowledge_values(knowledge_hits: Optional[List[Dict[str, Any]]], *keys: str) -> List[str]:
    values: List[str] = []
    for hit in knowledge_hits or []:
        meta = _normalize_hit_meta(hit)
        for key in keys:
            values.extend(_coerce_text_list(meta.get(key)))
    return _dedupe_pieces(values)


def _merge_profile_values(*groups: Any) -> List[str]:
    values: List[str] = []
    for group in groups:
        values.extend(_coerce_text_list(group))
    return _dedupe_pieces(values)


def _build_recommendation_profile(
    *,
    payload: Dict[str, Any],
    alias_filters: Optional[Dict[str, Any]],
    knowledge_hits: Optional[List[Dict[str, Any]]],
    base_criteria: Optional[Dict[str, Any]],
    region_filter: Optional[str] = None,
    region_context: Optional[str] = None,
) -> Dict[str, Any]:
    base_profile = {}
    if isinstance(base_criteria, dict):
        candidate = base_criteria.get("recommendation_profile")
        if isinstance(candidate, dict):
            base_profile = candidate

    profile = {
        "regions": _merge_region_contexts(
            region_filter,
            region_context,
            payload.get("region_context"),
            payload.get("region"),
            _extract_alias_filter_value(alias_filters, "region", "invn030"),
            _extract_knowledge_values(knowledge_hits, "region"),
            base_profile.get("regions"),
        ),
        "styles": _merge_profile_values(
            payload.get("style"),
            _extract_alias_filter_value(alias_filters, "style"),
            _extract_knowledge_values(knowledge_hits, "style", "wine_style"),
            base_profile.get("styles"),
        ),
        "grapes": _merge_profile_values(
            payload.get("grape"),
            _extract_alias_filter_value(alias_filters, "grape_varieties", "grape"),
            _extract_knowledge_values(knowledge_hits, "grape_varieties", "grape"),
            base_profile.get("grapes"),
        ),
        "classifications": _merge_profile_values(
            payload.get("classification"),
            _extract_alias_filter_value(alias_filters, "classification"),
            _extract_knowledge_values(knowledge_hits, "classification"),
            base_profile.get("classifications"),
        ),
        "villages": _merge_profile_values(
            payload.get("village"),
            _extract_alias_filter_value(alias_filters, "village"),
            _extract_knowledge_values(knowledge_hits, "village"),
            base_profile.get("villages"),
        ),
        "vineyards": _merge_profile_values(
            payload.get("vineyard"),
            _extract_alias_filter_value(alias_filters, "vineyard"),
            _extract_knowledge_values(knowledge_hits, "vineyard"),
            base_profile.get("vineyards"),
        ),
        "advice": _merge_profile_values(
            _extract_knowledge_values(knowledge_hits, "pairing", "body", "acidity", "tannin", "aging"),
            base_profile.get("advice"),
        ),
    }
    return {key: value for key, value in profile.items() if value}


def build_quote_search_keywords(criteria: Dict[str, Any], fallback_text: str = "") -> str:
    pieces: List[str] = []
    producer = _coerce_text(criteria.get("producer"))
    wine_name = _coerce_text(criteria.get("wine_name"))
    region = _coerce_text(criteria.get("region_filter")) or _coerce_text(criteria.get("region"))
    vintage = _coerce_text(criteria.get("vintage"))
    color = normalize_quote_color(criteria.get("color"))
    style = normalize_quote_style(criteria.get("style"))
    classification = _coerce_text(criteria.get("classification"))
    grape = _coerce_text(criteria.get("grape"))
    village = _coerce_text(criteria.get("village"))
    vineyard = _coerce_text(criteria.get("vineyard"))

    for value in (producer, wine_name, region, village, vineyard, classification, grape, vintage):
        if value:
            pieces.append(value)

    if color:
        pieces.append(_USER_COLOR_TO_QUERY.get(color, color))
    if style == "sparkling":
        pieces.append("sparkling wine")
        if region == "champagne":
            pieces.append("champagne")
    elif style == "still" and not color:
        pieces.append("still wine")

    if not pieces:
        stripped = _strip_intent_terms(_strip_price_mentions(fallback_text))
        if stripped:
            pieces.append(stripped)

    return " ".join(_dedupe_pieces(pieces))


def build_quote_query_variants(
    text: str,
    criteria: Dict[str, Any],
    supplied_variants: Optional[List[str]] = None,
) -> List[str]:
    variants: List[str] = []
    price_constraints = _extract_price_constraints(
        text,
        fallback_scope=_coerce_text(criteria.get("price_scope")),
    )
    vintage = _coerce_text(criteria.get("vintage"))
    color = normalize_quote_color(criteria.get("color"))
    style = normalize_quote_style(criteria.get("style"))
    producer = _coerce_text(criteria.get("producer"))
    wine_name = _coerce_text(criteria.get("wine_name"))
    region = _coerce_text(criteria.get("region_filter")) or _coerce_text(criteria.get("region"))
    classification = _coerce_text(criteria.get("classification"))
    grape = _coerce_text(criteria.get("grape"))
    village = _coerce_text(criteria.get("village"))
    vineyard = _coerce_text(criteria.get("vineyard"))
    keywords = _coerce_text(criteria.get("keywords"))

    # Quote retrieval only keeps variants derived from the user's explicit filters,
    # alias rewrites, or inherited quote context. Analysis-side freeform rewrites
    # can be useful for knowledge lookup, but should not inject unrelated producers
    # or labels into the CERP retrieval query.
    _ = supplied_variants
    raw_text = _coerce_text(_strip_price_mentions(text) if price_constraints else text)
    if raw_text:
        variants.append(raw_text)
        stripped = _strip_intent_terms(raw_text)
        if stripped and stripped != raw_text:
            variants.append(stripped)

    if keywords:
        variants.append(keywords)
    if producer and wine_name and vintage:
        variants.append(f"{producer} {wine_name} {vintage}")
    if producer and wine_name:
        variants.append(f"{producer} {wine_name}")
    if producer and region and vintage:
        variants.append(f"{producer} {region} {vintage}")
    if producer and vintage:
        variants.append(f"{producer} {vintage}")
    if wine_name and vintage:
        variants.append(f"{wine_name} {vintage}")
    if producer:
        variants.append(producer)
    if wine_name:
        variants.append(wine_name)
    if region:
        variants.append(region)
    if grape:
        variants.append(grape)
    if village:
        variants.append(village)
    if vineyard:
        variants.append(vineyard)
    if classification:
        variants.append(classification)
    if vintage and color:
        variants.append(f"{vintage} {_USER_COLOR_TO_QUERY.get(color, color)}")
    if vintage and region:
        variants.append(f"{region} {vintage}")
    if producer and color:
        variants.append(f"{producer} {_USER_COLOR_TO_QUERY.get(color, color)}")
    if region and color:
        variants.append(f"{region} {_USER_COLOR_TO_QUERY.get(color, color)}")
    if style == "sparkling":
        variants.append("champagne")
        if vintage:
            variants.append(f"{vintage} champagne")
    elif style == "still":
        variants.append("still wine")
    if vintage and grape:
        variants.append(f"{grape} {vintage}")
    if region and grape:
        variants.append(f"{region} {grape}")
    if village and vintage:
        variants.append(f"{village} {vintage}")
    if vineyard and vintage:
        variants.append(f"{vineyard} {vintage}")
    if vintage:
        variants.append(vintage)

    return _dedupe_pieces(variants)


def has_quote_semantic_filters(criteria: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(criteria, dict):
        return False
    for key in _HARD_CRITERIA_KEYS + _SOFT_CRITERIA_KEYS:
        if _coerce_text(criteria.get(key)):
            return True
    return False


def parse_quote_search_criteria(
    text: str,
    *,
    nlu_result: Optional[Dict[str, Any]] = None,
    quote_request: Optional[Dict[str, Any]] = None,
    alias_filters: Optional[Dict[str, Any]] = None,
    query_variants: Optional[List[str]] = None,
    knowledge_hits: Optional[List[Dict[str, Any]]] = None,
    base_criteria: Optional[Dict[str, Any]] = None,
    suppress_filters: Optional[List[str]] = None,
) -> Dict[str, Any]:
    normalized_text = normalize_quote_input_text(text)
    low_readability_query = is_low_readability_quote_query(text)
    payload = nlu_result if isinstance(nlu_result, dict) else {}
    inherited = base_criteria if isinstance(base_criteria, dict) else {}
    suppressed = {str(item).strip() for item in (suppress_filters or []) if str(item).strip()}
    price_constraints = _extract_price_constraints(
        normalized_text,
        fallback_scope=_first_nonempty(payload.get("price_scope"), inherited.get("price_scope")),
    )
    inferred_producer, inferred_wine_name = _infer_quote_named_entities(normalized_text)
    inherited_region_filter = _first_nonempty(inherited.get("region_filter"), inherited.get("region"))
    raw_region_context = _first_nonempty(
        payload.get("region_context"),
        payload.get("region"),
        inherited.get("region_context"),
        inherited.get("region"),
    )

    producer = None if "producer" in suppressed else _first_nonempty(
        payload.get("producer"),
        _extract_alias_filter_value(alias_filters, "invn006", "producer"),
        inferred_producer,
        inherited.get("producer"),
    )
    wine_name = None if "wine_name" in suppressed else _first_nonempty(
        payload.get("wine_name"),
        _extract_alias_filter_value(alias_filters, "invn005", "wine_name"),
        inferred_wine_name,
        inherited.get("wine_name"),
    )
    region = None if "region" in suppressed else _derive_quote_region_filter(
        normalized_text,
        payload.get("region_filter"),
        _extract_alias_filter_value(alias_filters, "region", "invn030"),
        raw_region_context,
        inherited_region_filter,
    )
    vintage = None if "vintage" in suppressed else _extract_vintage(
        normalized_text,
        _first_nonempty(payload.get("vintage"), inherited.get("vintage")),
    )
    if vintage and price_constraints:
        try:
            vintage_number = int(str(vintage).strip())
        except (TypeError, ValueError):
            vintage_number = None
        if vintage_number is not None:
            min_value = _parse_price_number(price_constraints.get("price_min"))
            max_value = _parse_price_number(price_constraints.get("price_max"))
            if (
                (min_value is not None and int(min_value) == vintage_number)
                or (max_value is not None and int(max_value) == vintage_number)
            ):
                vintage = None
    color = None if "color" in suppressed else (
        normalize_quote_color(normalized_text)
        or normalize_quote_color(payload.get("color"))
        or normalize_quote_color(inherited.get("color"))
    )
    style = None if "style" in suppressed else normalize_quote_style(normalized_text) or normalize_quote_style(payload.get("style"))
    if style is None and "style" not in suppressed:
        style = normalize_quote_style(
            _first_nonempty(
                _extract_alias_filter_value(alias_filters, "style"),
                inherited.get("style"),
            )
        )
    style = None if "style" in suppressed else _infer_default_still_style(normalized_text, color, style)

    recommendation_profile = _build_recommendation_profile(
        payload=payload,
        alias_filters=alias_filters,
        knowledge_hits=knowledge_hits,
        base_criteria=inherited,
        region_filter=region,
        region_context=raw_region_context,
    )

    criteria: Dict[str, Any] = {
        "producer": producer,
        "wine_name": wine_name,
        "region": region,
        "region_filter": region,
        "region_context": raw_region_context,
        "vintage": vintage,
        "color": color,
        "style": style,
        "classification": None if "classification" in suppressed else _infer_classification(
            normalized_text,
            _first_nonempty(
                _extract_alias_filter_value(alias_filters, "classification"),
                payload.get("classification"),
                inherited.get("classification"),
            ),
        ),
        "grape": None if "grape" in suppressed else _first_nonempty(
            _extract_alias_filter_value(alias_filters, "grape_varieties", "grape"),
            payload.get("grape"),
            inherited.get("grape"),
        ),
        "village": None if "village" in suppressed else _first_nonempty(
            _extract_alias_filter_value(alias_filters, "village"),
            payload.get("village"),
            inherited.get("village"),
        ),
        "vineyard": None if "vineyard" in suppressed else _first_nonempty(
            _extract_alias_filter_value(alias_filters, "vineyard"),
            payload.get("vineyard"),
            inherited.get("vineyard"),
        ),
        "result_limit": (quote_request or {}).get("result_limit"),
        "stock_policy": (quote_request or {}).get("stock_policy"),
        "price_min": None if "price_min" in suppressed else price_constraints.get("price_min"),
        "price_max": None if "price_max" in suppressed else price_constraints.get("price_max"),
        "price_scope": None if "price_scope" in suppressed else price_constraints.get("price_scope"),
        "low_readability_query": low_readability_query,
        "alias_filters": alias_filters or {},
        "recommendation_profile": recommendation_profile,
    }
    criteria["keywords"] = build_quote_search_keywords(criteria, fallback_text=normalized_text)
    criteria["query_variants"] = build_quote_query_variants(
        normalized_text,
        criteria,
        supplied_variants=limit_quote_query_variants(query_variants or [normalized_text], max_items=3),
    )
    return criteria


def _build_product_text(product: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("name", "name_en", "name_ch", "producer", "region", "rating", "color", "vintage", "no", "id"):
        value = _coerce_text(product.get(key))
        if value:
            parts.append(value)
    return " ".join(parts)


def _extract_product_vintage(product: Dict[str, Any]) -> Optional[str]:
    direct = _coerce_text(product.get("vintage"))
    if direct:
        match = _VINTAGE_RE.search(direct)
        if match:
            return match.group(1)
        return direct
    match = _VINTAGE_RE.search(_build_product_text(product))
    if match:
        return match.group(1)
    return None


def _product_has_vintage(product: Dict[str, Any], vintage: str) -> bool:
    target = _extract_vintage(str(vintage or ""))
    return bool(target) and _extract_product_vintage(product) == target


def _product_color(product: Dict[str, Any]) -> Optional[str]:
    direct = normalize_quote_color(product.get("color"))
    if direct:
        return direct
    return normalize_quote_color(_build_product_text(product))


def _product_style(product: Dict[str, Any]) -> Optional[str]:
    direct = normalize_quote_style(product.get("style"))
    if direct:
        return direct
    direct = normalize_quote_style(product.get("rating"))
    if direct:
        return direct
    return normalize_quote_style(_build_product_text(product))


def _product_region_text(product: Dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            _coerce_text(product.get("region")) or "",
            _build_product_text(product),
        ]
        if part
    ).strip()


def _product_region_is_reliable(product: Dict[str, Any]) -> bool:
    region = _coerce_text(product.get("region"))
    if not region:
        return False
    if re.fullmatch(r"[A-Z](?:-[A-Z0-9]+)+", region):
        return False
    if region.isupper() and len(region) <= 6:
        return False
    return True


def _product_style_is_reliable(product: Dict[str, Any]) -> bool:
    if normalize_quote_style(product.get("style")):
        return True
    rating = _coerce_text(product.get("rating"))
    if not rating:
        return False
    lowered = rating.casefold()
    return lowered in {"still", "sparkling", "champagne"}


def _normalized_contains(haystack: str, needle: str) -> bool:
    norm_haystack = _normalize_text(haystack)
    norm_needle = _normalize_text(needle)
    if not norm_haystack or not norm_needle:
        return False
    return norm_needle in norm_haystack


def _product_price(product: Dict[str, Any], scope: Optional[str] = None) -> Optional[float]:
    normalized_scope = _coerce_text(scope)
    if normalized_scope:
        normalized_scope = normalized_scope.lower()
    ordered_fields = {
        "vip": ("vip_price", "vip", "display_quote_price"),
        "list": ("list_price", "price", "display_quote_price", "vip_price", "fb_price", "wholesale_price"),
    }.get(normalized_scope or "list", ("list_price", "price", "vip_price", "fb_price", "wholesale_price"))
    for field in ordered_fields:
        value = _parse_price_number(product.get(field))
        if value is not None:
            return value
    return None


def _product_matches_classification(product: Dict[str, Any], classification: str) -> bool:
    if not classification:
        return True
    text = _build_product_text(product)
    if _BLANC_DE_BLANCS_RE.search(classification):
        return bool(_BLANC_DE_BLANCS_RE.search(text))
    return _normalized_contains(text, classification)


def quote_product_matches_criteria(product: Dict[str, Any], criteria: Optional[Dict[str, Any]]) -> bool:
    return len(quote_product_exact_rejection_reasons(product, criteria)) == 0


def quote_product_exact_rejection_reasons(product: Dict[str, Any], criteria: Optional[Dict[str, Any]]) -> List[str]:
    if not isinstance(criteria, dict):
        return []

    producer = _coerce_text(criteria.get("producer"))
    wine_name = _coerce_text(criteria.get("wine_name"))
    region = _coerce_text(criteria.get("region"))
    vintage = _coerce_text(criteria.get("vintage"))
    color = normalize_quote_color(criteria.get("color"))
    style = normalize_quote_style(criteria.get("style"))
    classification = _coerce_text(criteria.get("classification"))
    price_min = criteria.get("price_min")
    price_max = criteria.get("price_max")
    price_scope = _coerce_text(criteria.get("price_scope"))
    text = _build_product_text(product)
    identity_match = quote_product_identity_score(product, criteria) > 0
    reasons: List[str] = []

    if not identity_match and producer and not _normalized_contains(_coerce_text(product.get("producer")) or text, producer):
        reasons.append("producer_mismatch")
    if not identity_match and wine_name and not _normalized_contains(text, wine_name):
        reasons.append("wine_name_mismatch")
    if vintage and not _product_has_vintage(product, vintage):
        reasons.append("vintage_mismatch")
    if color and _product_color(product) != color:
        reasons.append("color_mismatch")
    if classification and not _product_matches_classification(product, classification):
        reasons.append("classification_mismatch")
    if region and _product_region_is_reliable(product) and not _normalized_contains(_product_region_text(product), region):
        reasons.append("region_mismatch")
    elif region and region.casefold() == "champagne" and _CREMANT_RE.search(text):
        reasons.append("region_mismatch")
    if style and _product_style_is_reliable(product) and _product_style(product) != style:
        reasons.append("style_mismatch")
    scoped_price = _product_price(product, price_scope)
    if price_min is not None and (scoped_price is None or scoped_price < float(price_min)):
        reasons.append("price_below_min")
    if price_max is not None and (scoped_price is None or scoped_price > float(price_max)):
        reasons.append("price_above_max")
    return reasons


def quote_product_match_score(product: Dict[str, Any], criteria: Optional[Dict[str, Any]]) -> float:
    if not isinstance(criteria, dict):
        return 0.0
    if not quote_product_matches_criteria(product, criteria):
        return 0.0

    score = 0.0
    identity_score = quote_product_identity_score(product, criteria)
    if identity_score:
        score += identity_score
    if _coerce_text(criteria.get("producer")):
        score += 3.0
    if _coerce_text(criteria.get("wine_name")):
        score += 3.0
    if _coerce_text(criteria.get("region")) and _product_region_is_reliable(product):
        score += 2.0
    if _coerce_text(criteria.get("vintage")):
        score += 2.0
    if normalize_quote_color(criteria.get("color")):
        score += 2.0
    if normalize_quote_style(criteria.get("style")) and _product_style_is_reliable(product):
        score += 2.0
    if _coerce_text(criteria.get("classification")):
        score += 1.5
    if criteria.get("price_min") is not None or criteria.get("price_max") is not None:
        score += 1.5
    recommendation_profile = criteria.get("recommendation_profile") if isinstance(criteria, dict) else {}
    if isinstance(recommendation_profile, dict):
        for region in _coerce_text_list(recommendation_profile.get("regions")):
            if _normalized_contains(_product_region_text(product), region):
                score += 0.5
                break
        for style in _coerce_text_list(recommendation_profile.get("styles")):
            if normalize_quote_style(style) and _product_style(product) == normalize_quote_style(style):
                score += 0.5
                break
    stock_value = product.get("stock") if product.get("stock") is not None else product.get("stock_qty")
    try:
        if float(stock_value or 0) > 0:
            score += 0.25
    except (TypeError, ValueError):
        pass
    return score


def quote_product_alternative_score(product: Dict[str, Any], criteria: Optional[Dict[str, Any]]) -> float:
    if not isinstance(criteria, dict):
        return 0.0
    if quote_product_matches_criteria(product, criteria):
        return 0.0

    score = 0.0
    text = _build_product_text(product)
    producer = _coerce_text(criteria.get("producer"))
    wine_name = _coerce_text(criteria.get("wine_name"))
    region = _coerce_text(criteria.get("region"))
    vintage = _coerce_text(criteria.get("vintage"))
    color = normalize_quote_color(criteria.get("color"))
    style = normalize_quote_style(criteria.get("style"))
    classification = _coerce_text(criteria.get("classification"))
    price_min = criteria.get("price_min")
    price_max = criteria.get("price_max")
    price_scope = _coerce_text(criteria.get("price_scope"))
    recommendation_profile = criteria.get("recommendation_profile") if isinstance(criteria, dict) else {}

    identity_score = quote_product_identity_score(product, criteria)
    if identity_score:
        score += identity_score
    if producer and _normalized_contains(_coerce_text(product.get("producer")) or text, producer):
        score += 5.0
    if wine_name and _normalized_contains(text, wine_name):
        score += 4.0
    if region and _normalized_contains(_product_region_text(product), region):
        score += 3.0
    if color and _product_color(product) == color:
        score += 2.5
    if style and _product_style(product) == style:
        score += 2.5
    if classification and _product_matches_classification(product, classification):
        score += 2.0
    if region and region.casefold() == "champagne" and _CREMANT_RE.search(text):
        return 0.0

    for key in _SOFT_CRITERIA_KEYS:
        value = _coerce_text(criteria.get(key))
        if value and _normalized_contains(text, value):
            score += 1.5

    if isinstance(recommendation_profile, dict):
        for region_hint in _coerce_text_list(recommendation_profile.get("regions")):
            if region_hint and _normalized_contains(_product_region_text(product), region_hint):
                score += 1.5
                break
        for style_hint in _coerce_text_list(recommendation_profile.get("styles")):
            normalized_style = normalize_quote_style(style_hint)
            if normalized_style and _product_style(product) == normalized_style:
                score += 1.25
                break
        for grape_hint in _coerce_text_list(recommendation_profile.get("grapes")):
            if grape_hint and _normalized_contains(text, grape_hint):
                score += 1.0
                break
        for classification_hint in _coerce_text_list(recommendation_profile.get("classifications")):
            if classification_hint and _normalized_contains(text, classification_hint):
                score += 1.0
                break

    if vintage:
        product_vintage = _extract_product_vintage(product)
        if product_vintage and product_vintage.isdigit() and vintage.isdigit():
            diff = abs(int(product_vintage) - int(vintage))
            if diff == 0:
                score += 3.0
            elif diff <= 1:
                score += 2.0
            elif diff <= 3:
                score += 1.0

    scoped_price = _product_price(product, price_scope)
    if scoped_price is not None and (price_min is not None or price_max is not None):
        if price_min is not None and scoped_price >= float(price_min):
            score += 1.0
        if price_max is not None and scoped_price <= float(price_max):
            score += 1.0

    stock_value = product.get("stock") if product.get("stock") is not None else product.get("stock_qty")
    try:
        if float(stock_value or 0) > 0:
            score += 0.5
    except (TypeError, ValueError):
        pass
    return score


def build_quote_match_summary(
    criteria: Optional[Dict[str, Any]],
    *,
    exact_count: int,
    alternative_count: int,
) -> Dict[str, Any]:
    normalized_criteria: Dict[str, Any] = {}
    if isinstance(criteria, dict):
        for key in _HARD_CRITERIA_KEYS + _SOFT_CRITERIA_KEYS:
            value = criteria.get(key)
            if value not in (None, "", [], {}):
                normalized_criteria[key] = value
    mode = "exact" if exact_count > 0 else "alternatives" if alternative_count > 0 else "empty"
    return {
        "mode": mode,
        "exact_count": exact_count,
        "alternative_count": alternative_count,
        "applied_filters": normalized_criteria,
    }
