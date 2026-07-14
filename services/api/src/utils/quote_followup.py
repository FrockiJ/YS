from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, List, Optional

ACTION_RELAX_CONSTRAINTS = "relax_constraints_and_regenerate"
ACTION_SHOW_RECOMMENDED = "show_recommended_alternatives"
ACTION_INCLUDE_SIMILAR = "include_similar_in_stock"
ACTION_FILL_SIMILAR = "fill_with_similar_until_target"
ACTION_CONTINUE = "continue_with_same_context"

_FILTER_KEYS = (
    "producer",
    "wine_name",
    "region",
    "vintage",
    "color",
    "style",
    "classification",
    "grape",
    "village",
    "vineyard",
    "price_min",
    "price_max",
    "price_scope",
    "result_limit",
    "stock_policy",
)

_RELAXATION_ORDER = ("vintage", "region", "color")

_CONFIRMATION_TERMS = {
    "\u597d",
    "\u597d\u7684",
    "\u597d\u554a",
    "\u597d\u5594",
    "\u597d\u5440",
    "\u53ef\u4ee5",
    "\u53ef\u4ee5\u554a",
    "\u9858\u610f",
    "\u6c92\u554f\u984c",
    "ok",
    "okay",
    "yes",
    "yep",
    "sure",
}

_ACTION_VALUES = {
    ACTION_RELAX_CONSTRAINTS,
    ACTION_SHOW_RECOMMENDED,
    ACTION_INCLUDE_SIMILAR,
    ACTION_FILL_SIMILAR,
    ACTION_CONTINUE,
}

_STOCK_PATTERNS = (
    r"\u6709\u73fe\u8ca8",
    r"\u73fe\u8ca8",
    r"\u6709\u5eab\u5b58",
    r"\u5eab\u5b58",
    r"\u6709\u8ca8",
    r"in[\s-]?stock",
    r"inventory",
)

_QUANTITY_ONLY_RE = re.compile(
    r"^(?:\u90a3|\u8981|\u6539\u6210|\u7d66\u6211|\u4f86|\u770b|\u518d)?\s*(\d+)\s*(?:\u74f6|\u652f|\u7bb1|\u7d44|\u6b3e|wine|wines|bottle|bottles|case|cases|pack|packs)\s*$",
    flags=re.IGNORECASE,
)

_SHORT_REFINEMENT_PATTERNS = (
    r"\u767d\u7684",
    r"\u7d05\u7684",
    r"\u7c89\u7d05",
    r"\u6c23\u6ce1",
    r"\u9999\u6ab3",
    r"\u9999\u6a9f",
    r"\u6a58\u9152",
    r"\u540c\u50f9\u4f4d",
    r"\u4fbf\u5b9c\u4e00\u9ede",
    r"\u8cb4\u4e00\u9ede",
    r"\u518d\u591a\u5e7e\u6b3e",
    r"\u591a\u5e7e\u6b3e",
    r"\u5176\u4ed6\u63a8\u85a6",
)

_SHOW_MORE_PATTERNS = (
    r"\u770b\u66f4\u591a",
    r"\u66f4\u591a",
    r"\u518d\u591a\u4e00\u9ede",
    r"\u518d\u591a\u4e00\u4e9b",
    r"\u518d\u4f86\u4e00\u4e9b",
)

_SIMILAR_COMPLETION_PATTERNS = (
    r"\u985e\u4f3c",
    r"\u76f8\u4f3c",
    r"\u63a5\u8fd1",
    r"\u88dc\u5920",
    r"\u88dc\u8db3",
    r"\u88dc\u6eff",
    r"\u6e4a\u8db3",
    r"\u6e4a\u5920",
    r"\u6e4a\u6eff",
    r"\u88dc\u9f4a",
    r"\u518d\u88dc",
)

_SIMILARITY_HINT_PATTERNS = (
    r"\u985e\u4f3c",
    r"\u76f8\u4f3c",
    r"\u63a5\u8fd1",
)

_SIMILAR_COMPLETION_TARGET_RE = re.compile(
    r"(\d+)\s*(?:\u74f6|\u652f|\u7bb1|\u7d44|\u6b3e|wine|wines|bottle|bottles|case|cases|pack|packs)",
    flags=re.IGNORECASE,
)

_SIMILAR_COMPLETION_ADD_RE = re.compile(
    r"\u518d\u88dc\s*(\d+)\s*(?:\u74f6|\u652f|\u7bb1|\u7d44|\u6b3e|wine|wines|bottle|bottles|case|cases|pack|packs)",
    flags=re.IGNORECASE,
)


def _coerce_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_int(value: Any) -> Optional[int]:
    if value in (None, "", [], {}):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        resolved = _coerce_int(value)
        if resolved is not None:
            return resolved
    return None


def _coerce_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _normalize_text(text: str) -> str:
    compact = re.sub(r"\s+", "", (text or "").strip()).casefold()
    return re.sub(r"[，。！？!?,、．…~～「」『』（）()]+", "", compact)


def _join_queries(base_query: Optional[str], text: str) -> str:
    base = _coerce_text(base_query)
    tail = _coerce_text(text)
    if base and tail:
        if tail.casefold() in base.casefold():
            return base
        return f"{base} {tail}".strip()
    return base or tail or ""


def _dedupe_products(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        code = _coerce_text(item.get("no") or item.get("id") or item.get("product_no"))
        key = code or _coerce_text(item.get("name") or item.get("name_en") or item.get("name_ch"))
        if not key:
            continue
        token = key.casefold()
        if token in seen:
            continue
        seen.add(token)
        results.append(dict(item))
    return results


def _append_unique_action(actions: List[str], action: Optional[str]) -> None:
    value = _coerce_text(action)
    if value and value not in actions:
        actions.append(value)


def _with_match_type(items: List[Dict[str, Any]], match_type: str) -> List[Dict[str, Any]]:
    tagged: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        normalized.setdefault("match_type", match_type)
        normalized.setdefault("quote_item_origin", match_type)
        tagged.append(normalized)
    return tagged


def _filtered_requested_filters(value: Any) -> Dict[str, Any]:
    source = _coerce_mapping(value)
    return {
        key: deepcopy(item)
        for key, item in source.items()
        if key in _FILTER_KEYS and item not in (None, "", [], {})
    }


def is_bare_confirmation(text: str) -> bool:
    normalized = _normalize_text(text)
    return normalized in {_normalize_text(term) for term in _CONFIRMATION_TERMS}


def _is_stock_followup(text: str) -> bool:
    raw = _coerce_text(text) or ""
    return any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in _STOCK_PATTERNS)


def _is_quantity_followup(text: str) -> bool:
    raw = _coerce_text(text) or ""
    return bool(_QUANTITY_ONLY_RE.match(raw))


def _is_short_refinement(text: str) -> bool:
    raw = _coerce_text(text) or ""
    if not raw or len(raw) > 16:
        return False
    return any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in _SHORT_REFINEMENT_PATTERNS)


def _is_show_more_followup(text: str) -> bool:
    raw = _coerce_text(text) or ""
    if not raw or len(raw) > 16:
        return False
    return any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in _SHOW_MORE_PATTERNS)


def _is_meaningful_query(text: Optional[str]) -> bool:
    if not _coerce_text(text):
        return False
    return not is_bare_confirmation(text or "")


def _resolve_canonical_query(source: Dict[str, Any], stored_followup: Dict[str, Any]) -> str:
    context_resolution = _coerce_mapping(source.get("context_resolution"))
    candidates = [
        stored_followup.get("canonical_query"),
        source.get("canonical_query"),
        context_resolution.get("canonical_query"),
        stored_followup.get("base_query"),
        context_resolution.get("display_query"),
        source.get("query"),
        source.get("resolved_query"),
        source.get("raw_query"),
        source.get("search_query"),
    ]
    for candidate in candidates:
        text = _coerce_text(candidate)
        if _is_meaningful_query(text):
            return text or ""
    for candidate in candidates:
        text = _coerce_text(candidate)
        if text:
            return text
    return ""


def _resolve_similarity_target_count(text: str, contract: Dict[str, Any]) -> Optional[int]:
    raw = _coerce_text(text) or ""
    default_target = _coerce_int(contract.get("target_count"))
    exact_count = _coerce_int(contract.get("exact_count")) or len(_coerce_items(contract.get("quote_items")))

    additive_match = _SIMILAR_COMPLETION_ADD_RE.search(raw)
    if additive_match:
        try:
            return exact_count + int(additive_match.group(1))
        except (TypeError, ValueError):
            return default_target

    target_match = _SIMILAR_COMPLETION_TARGET_RE.search(raw)
    if target_match:
        try:
            return int(target_match.group(1))
        except (TypeError, ValueError):
            return default_target

    return default_target


def _is_similarity_completion_followup(text: str, contract: Dict[str, Any]) -> bool:
    raw = _coerce_text(text) or ""
    if not raw:
        return False
    has_completion_signal = any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in _SIMILAR_COMPLETION_PATTERNS)
    if not has_completion_signal:
        return False

    target_count = _resolve_similarity_target_count(raw, contract)
    exact_count = _coerce_int(contract.get("exact_count")) or len(_coerce_items(contract.get("quote_items")))
    remaining_needed = _coerce_int(contract.get("remaining_needed")) or 0
    pending_goal = _coerce_text(contract.get("pending_goal"))
    has_similarity_hint = any(re.search(pattern, raw, flags=re.IGNORECASE) for pattern in _SIMILARITY_HINT_PATTERNS)

    if target_count is not None and target_count > exact_count:
        return True
    if remaining_needed > 0 and (has_similarity_hint or pending_goal == ACTION_FILL_SIMILAR):
        return True
    return False


def build_quote_followup_contract(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    source = _coerce_mapping(metadata)
    stored_followup = _coerce_mapping(source.get("quote_followup"))
    requested_filters = (
        _filtered_requested_filters(stored_followup.get("requested_filters"))
        or _filtered_requested_filters(source.get("requested_filters"))
        or _filtered_requested_filters(source.get("search_criteria"))
    )
    recommendation_profile = (
        deepcopy(_coerce_mapping(stored_followup.get("recommendation_profile")))
        or deepcopy(_coerce_mapping(source.get("recommendation_profile")))
        or deepcopy(_coerce_mapping(requested_filters.get("recommendation_profile")))
    )
    recommended_alternatives = (
        _coerce_items(stored_followup.get("recommended_alternatives"))
        or _coerce_items(source.get("recommended_alternatives"))
    )
    suggested_alternatives = _coerce_items(source.get("suggested_alternatives"))
    exact_quote_items = (
        _coerce_items(stored_followup.get("exact_quote_items"))
        or _coerce_items(source.get("exact_quote_items"))
        or _coerce_items(source.get("quote_items"))
    )
    quote_items = _coerce_items(source.get("quote_items"))
    current_quote_count = len(quote_items)
    match_summary = _coerce_mapping(source.get("match_summary"))
    stock_policy = _coerce_text(source.get("stock_policy")) or _coerce_text(requested_filters.get("stock_policy"))
    canonical_query = _resolve_canonical_query(source, stored_followup)
    target_count = _first_int(
        stored_followup.get("target_count"),
        source.get("target_count"),
        source.get("applied_result_limit"),
        source.get("result_limit"),
        requested_filters.get("result_limit"),
    )
    exact_count = _first_int(
        stored_followup.get("exact_count"),
        source.get("exact_count"),
        source.get("exact_candidate_count"),
        len(exact_quote_items),
    ) or 0
    stored_remaining_needed = _first_int(
        stored_followup.get("remaining_needed"),
        source.get("remaining_needed"),
    )
    remaining_needed = (
        stored_remaining_needed
        if stored_remaining_needed is not None
        else max((target_count or 0) - exact_count, 0)
    )
    fill_strategy = (
        _coerce_text(stored_followup.get("fill_strategy"))
        or _coerce_text(source.get("fill_strategy"))
        or ("exact_first_then_similar_fill" if target_count and exact_count < target_count else None)
    )

    default_confirm_action = _coerce_text(stored_followup.get("default_confirm_action")) or _coerce_text(
        source.get("default_confirm_action")
    )
    pending_goal = _coerce_text(stored_followup.get("pending_goal")) or _coerce_text(source.get("pending_goal"))
    available_actions = [
        str(item).strip()
        for item in (stored_followup.get("available_actions") or source.get("available_actions") or [])
        if str(item).strip()
    ]

    if not default_confirm_action:
        if recommended_alternatives and (not exact_quote_items or match_summary.get("mode") == "alternatives"):
            default_confirm_action = ACTION_RELAX_CONSTRAINTS
        elif suggested_alternatives and exact_quote_items and stock_policy == "in_stock_only":
            default_confirm_action = ACTION_INCLUDE_SIMILAR
        elif (
            recommended_alternatives
            and exact_quote_items
            and target_count
            and current_quote_count < target_count
            and stock_policy != "in_stock_only"
        ):
            default_confirm_action = ACTION_FILL_SIMILAR
        else:
            default_confirm_action = ACTION_CONTINUE
    if not pending_goal:
        pending_goal = default_confirm_action

    if not available_actions:
        available_actions = []
        _append_unique_action(available_actions, default_confirm_action)
        if (
            recommended_alternatives
            and exact_quote_items
            and target_count
            and current_quote_count < target_count
            and stock_policy != "in_stock_only"
        ):
            _append_unique_action(available_actions, ACTION_FILL_SIMILAR)
        if recommended_alternatives and ACTION_RELAX_CONSTRAINTS not in available_actions and not exact_quote_items:
            _append_unique_action(available_actions, ACTION_RELAX_CONSTRAINTS)
        if recommended_alternatives:
            _append_unique_action(available_actions, ACTION_SHOW_RECOMMENDED)
        if suggested_alternatives and exact_quote_items and stock_policy == "in_stock_only":
            _append_unique_action(available_actions, ACTION_INCLUDE_SIMILAR)
        if (quote_items or requested_filters) and ACTION_CONTINUE not in available_actions:
            _append_unique_action(available_actions, ACTION_CONTINUE)

    return {
        "base_query": canonical_query,
        "canonical_query": canonical_query,
        "raw_query": _coerce_text(source.get("raw_query")) or "",
        "requested_filters": requested_filters,
        "recommendation_profile": recommendation_profile,
        "exact_quote_items": exact_quote_items,
        "recommended_alternatives": recommended_alternatives,
        "suggested_alternatives": suggested_alternatives,
        "quote_items": quote_items,
        "stock_policy": stock_policy,
        "target_count": target_count,
        "exact_count": exact_count,
        "remaining_needed": remaining_needed,
        "fill_strategy": fill_strategy,
        "default_confirm_action": default_confirm_action,
        "pending_goal": pending_goal,
        "available_actions": available_actions,
        "match_summary": match_summary,
    }


def resolve_quote_followup(
    text: str,
    metadata: Optional[Dict[str, Any]],
    *,
    requested_action: Optional[str] = None,
    action_source: Optional[str] = None,
) -> Dict[str, Any]:
    contract = build_quote_followup_contract(metadata)
    canonical_query = _coerce_text(contract.get("canonical_query"))
    has_base_context = bool(
        canonical_query
        or contract.get("requested_filters")
        or contract.get("quote_items")
        or contract.get("recommended_alternatives")
    )
    is_confirmation = is_bare_confirmation(text)
    is_stock = _is_stock_followup(text)
    is_quantity = _is_quantity_followup(text)
    is_refinement = _is_short_refinement(text)
    is_show_more = _is_show_more_followup(text)
    is_similarity_completion = _is_similarity_completion_followup(text, contract)
    requested_action_value = _coerce_text(requested_action)
    explicit_action_requested = bool(
        requested_action_value
        and requested_action_value in _ACTION_VALUES
        and (
            requested_action_value == contract.get("default_confirm_action")
            or requested_action_value == contract.get("pending_goal")
            or requested_action_value in (contract.get("available_actions") or [])
        )
    )
    is_followup = has_base_context and (
        explicit_action_requested
        or is_confirmation
        or is_stock
        or is_quantity
        or is_refinement
        or is_show_more
        or is_similarity_completion
    )

    followup_action = None
    request_overrides: Dict[str, Any] = {}
    raw_query = _coerce_text(text) or ""
    resolved_query = raw_query
    followup_action_source = None
    followup_confirmation_matched = False

    if is_followup:
        if explicit_action_requested:
            followup_action = requested_action_value
            followup_action_source = _coerce_text(action_source) or "button"
            if followup_action == ACTION_FILL_SIMILAR:
                target_count = _coerce_int(contract.get("target_count"))
                if target_count:
                    request_overrides["result_limit"] = target_count
                    request_overrides["fill_strategy"] = contract.get("fill_strategy") or "exact_first_then_similar_fill"
            resolved_query = canonical_query or raw_query
        elif is_confirmation:
            followup_action = contract.get("default_confirm_action") or ACTION_CONTINUE
            followup_confirmation_matched = True
            followup_action_source = "bare_confirmation"
            if followup_action == ACTION_FILL_SIMILAR:
                target_count = _coerce_int(contract.get("target_count"))
                if target_count:
                    request_overrides["result_limit"] = target_count
                    request_overrides["fill_strategy"] = contract.get("fill_strategy") or "exact_first_then_similar_fill"
            resolved_query = canonical_query or raw_query
        elif is_similarity_completion:
            followup_action = ACTION_FILL_SIMILAR
            followup_action_source = "explicit_text"
            target_count = _resolve_similarity_target_count(raw_query, contract)
            if target_count:
                request_overrides["result_limit"] = target_count
            request_overrides["fill_strategy"] = contract.get("fill_strategy") or "exact_first_then_similar_fill"
            resolved_query = canonical_query or raw_query
        else:
            followup_action = ACTION_CONTINUE
            followup_action_source = "explicit_text"
            if is_show_more:
                existing_target = _coerce_int(contract.get("target_count")) or len(contract.get("quote_items") or [])
                request_overrides["result_limit"] = min(max(existing_target, 20) + 20, 100)
                resolved_query = canonical_query or raw_query
            elif is_stock:
                request_overrides["stock_policy"] = "in_stock_only"
                resolved_query = canonical_query or raw_query
            else:
                resolved_query = _join_queries(canonical_query, raw_query)

    return {
        "canonical_query": canonical_query or raw_query,
        "raw_query": raw_query,
        "resolved_query": resolved_query,
        "is_followup": is_followup,
        "followup_action": followup_action,
        "followup_confirmation_matched": followup_confirmation_matched,
        "followup_action_source": followup_action_source,
        "followup_contract_version": "v2",
        "pending_goal": contract.get("pending_goal"),
        "base_quote_context": contract,
        "request_overrides": request_overrides,
    }


def materialize_quote_followup_action(
    metadata: Optional[Dict[str, Any]],
    action: Optional[str],
    *,
    result_limit: Optional[int] = None,
    line_item_quantity: int = 1,
) -> Dict[str, Any]:
    contract = build_quote_followup_contract(metadata)
    exact_quote_items = _with_match_type(
        _coerce_items(contract.get("exact_quote_items")) or _coerce_items(contract.get("quote_items")),
        "exact",
    )
    quote_items = _with_match_type(_coerce_items(contract.get("quote_items")), "exact")
    recommended_alternatives = _coerce_items(contract.get("recommended_alternatives"))
    suggested_alternatives = _coerce_items(contract.get("suggested_alternatives"))

    if action == ACTION_SHOW_RECOMMENDED:
        products = _with_match_type(recommended_alternatives, "alternative")
    elif action == ACTION_INCLUDE_SIMILAR:
        products = exact_quote_items + _with_match_type(suggested_alternatives, "similar_in_stock")
    elif action == ACTION_FILL_SIMILAR:
        target_count = _coerce_int(result_limit) or _coerce_int(contract.get("target_count"))
        similar_candidates = _with_match_type(recommended_alternatives, "similar_fill")
        if target_count and target_count > 0:
            needed = max(target_count - len(exact_quote_items), 0)
            products = exact_quote_items[:target_count] + similar_candidates[:needed]
        else:
            products = exact_quote_items + similar_candidates
    else:
        products = exact_quote_items or quote_items

    products = _dedupe_products(products)
    if result_limit and result_limit > 0:
        products = products[:result_limit]

    quantity = max(int(line_item_quantity or 1), 1)
    for item in products:
        item["quantity"] = quantity

    return {
        "products": products,
        "exact_products": exact_quote_items,
        "recommended_alternatives": recommended_alternatives,
        "suggested_alternatives": suggested_alternatives,
        "contract": contract,
    }


def relax_quote_followup_filters(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    contract = build_quote_followup_contract(metadata)
    before_filters = _filtered_requested_filters(contract.get("requested_filters"))
    after_filters = deepcopy(before_filters)
    suppressed_filters: List[str] = []

    for key in _RELAXATION_ORDER:
        if after_filters.get(key) not in (None, "", [], {}):
            after_filters.pop(key, None)
            suppressed_filters.append(key)
            break

    return {
        "requested_filters": after_filters,
        "relaxed_filters_before": before_filters,
        "relaxed_filters_after": after_filters,
        "suppressed_filters": suppressed_filters,
    }
