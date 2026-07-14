from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ...schemas.ai import Hit
from .citation_validator import normalize_source_metadata


LICENSED_REVIEW_CATEGORIES = {"exact_review_lookup", "multi_review_compare"}
BOOK_CATEGORIES = {"book_corpus_lookup", "internal_rag_only_validation"}
CERP_CATEGORIES = {
    "quote_recommendation",
    "inventory_lookup",
    "url_product_lookup",
    "image_product_lookup",
    "alias_inventory_equivalence",
    "cerp_business_lookup",
}
SOURCE_HIERARCHY_CATEGORIES = {"source_hierarchy_conflict"}
CUSTOMER_FACT_CATEGORIES = {"customer_facts_pack"}
PERMISSION_BOUNDARY_CATEGORIES = {"permission_boundary"}

SOURCE_NAME_ALIASES = {
    "burghound": ("burghound",),
    "inside_burgundy": ("jasper morris", "inside burgundy", "inside_burgundy", "jasper"),
    "vinous": ("vinous",),
    "wine_advocate": ("wine advocate", "robert parker", "parker"),
    "wine_spectator": ("wine spectator", "spectator"),
}

REVIEW_REQUIRED_METADATA = ("producer", "wine_name", "vintage", "source_name", "reviewer", "score")
BOOK_REQUIRED_METADATA = ("source_name", "page")


def apply_evidence_contract(
    *,
    query: str,
    prompt_category: Optional[str],
    entity_hints: Optional[Dict[str, Any]],
    selected_hits: Sequence[Hit],
    cerp_products: Sequence[Dict[str, Any]],
    source_policy: Optional[str],
    route_policy: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Hit], Dict[str, Any]]:
    """Apply hard evidence gates before answer generation.

    The citation validator proves that citations are auditable. This layer proves
    that the selected evidence is the right kind of evidence for the route.
    """

    category = str(prompt_category or "").strip()
    evidence_type = evidence_type_for_prompt_category(category)
    plan: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "prompt_category": category,
        "source_policy": source_policy,
        "status": "not_required" if evidence_type == "grounded_answer" else "pass",
        "missing_contract_fields": [],
        "hard_error_flags": [],
        "score_breakdown": [],
        "route_policy": route_policy or {},
        "selected_hit_count_before_contract": len(list(selected_hits or [])),
        "cerp_proof_count": len(list(cerp_products or [])),
    }

    if evidence_type == "grounded_answer":
        if selected_hits:
            plan["status"] = "pass"
            plan["answer_plan"] = _build_generic_answer_plan(evidence_type, selected_hits)
            plan["selected_hit_count_after_contract"] = len(list(selected_hits or []))
        else:
            plan["status"] = "no_evidence"
            plan["answer_plan"] = {"items": [], "allowed_claims": []}
            plan["selected_hit_count_after_contract"] = 0
        return list(selected_hits or []), plan
    if evidence_type == "permission_boundary":
        return [], _fail(plan, "permission_boundary_requires_explicit_authorization", ["permission"])
    if evidence_type == "cerp_snapshot":
        if cerp_products or _hits_have_cerp_proof(selected_hits):
            plan["answer_plan"] = _build_cerp_answer_plan(cerp_products, selected_hits)
            if category == "cerp_business_lookup":
                plan["evidence_type"] = "cerp_business_snapshot"
            plan["selected_hit_count_after_contract"] = len(list(selected_hits or []))
            return list(selected_hits or []), plan
        return [], _fail(plan, "cerp_snapshot_missing", ["cerp_results"])
    if evidence_type == "source_hierarchy":
        if cerp_products or _hits_have_cerp_proof(selected_hits) or selected_hits:
            if cerp_products or _hits_have_cerp_proof(selected_hits):
                plan["answer_plan"] = _build_cerp_answer_plan(cerp_products, selected_hits)
            else:
                plan["answer_plan"] = _build_generic_answer_plan(evidence_type, selected_hits)
            plan["selected_hit_count_after_contract"] = len(list(selected_hits or []))
            return list(selected_hits or []), plan
        return [], _fail(plan, "source_hierarchy_evidence_missing", ["source_hierarchy_fixture"])
    if evidence_type == "licensed_review":
        return _apply_review_contract(
            query=query,
            category=category,
            entity_hints=entity_hints or {},
            selected_hits=selected_hits,
            plan=plan,
        )
    if evidence_type == "book_ocr":
        return _apply_book_contract(
            query=query,
            entity_hints=entity_hints or {},
            selected_hits=selected_hits,
            plan=plan,
        )
    if evidence_type == "customer_facts_pack":
        return _apply_customer_facts_contract(selected_hits=selected_hits, plan=plan)
    return list(selected_hits or []), plan


def evidence_type_for_prompt_category(prompt_category: Optional[str]) -> str:
    category = str(prompt_category or "").strip()
    if category in LICENSED_REVIEW_CATEGORIES:
        return "licensed_review"
    if category in BOOK_CATEGORIES:
        return "book_ocr"
    if category in CERP_CATEGORIES:
        return "cerp_snapshot"
    if category in SOURCE_HIERARCHY_CATEGORIES:
        return "source_hierarchy"
    if category in CUSTOMER_FACT_CATEGORIES:
        return "customer_facts_pack"
    if category in PERMISSION_BOUNDARY_CATEGORIES:
        return "permission_boundary"
    return "grounded_answer"


def build_cerp_evidence_contract(
    *,
    cerp_products: Sequence[Dict[str, Any]],
    prompt_category: str = "quote_recommendation",
    source_policy: str = "internal_only",
    route_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _selected, plan = apply_evidence_contract(
        query="",
        prompt_category=prompt_category,
        entity_hints={},
        selected_hits=[],
        cerp_products=cerp_products,
        source_policy=source_policy,
        route_policy=route_policy,
    )
    return plan


def answer_plan_summary(plan: Dict[str, Any]) -> str:
    answer_plan = plan.get("answer_plan") if isinstance(plan.get("answer_plan"), dict) else {}
    if not answer_plan:
        return ""
    lines = [
        f"Evidence contract: {plan.get('evidence_type')}",
        "Use only the evidence items below for factual claims.",
        "If a claim is not supported by these items, say the data is insufficient.",
    ]
    for idx, item in enumerate(answer_plan.get("items") or [], start=1):
        trace = item.get("source_trace") or item.get("id") or f"item {idx}"
        excerpt = str(item.get("excerpt") or "").replace("\n", " ").strip()
        if len(excerpt) > 700:
            excerpt = excerpt[:700].rstrip() + "..."
        lines.append(f"{idx}. {trace}: {excerpt}")
    return "\n".join(lines)


def _apply_review_contract(
    *,
    query: str,
    category: str,
    entity_hints: Dict[str, Any],
    selected_hits: Sequence[Hit],
    plan: Dict[str, Any],
) -> Tuple[List[Hit], Dict[str, Any]]:
    requested_sources = _requested_source_names(query)
    scored: List[Tuple[float, Hit, Dict[str, Any]]] = []
    for hit in selected_hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        family = str(meta.get("source_family") or "").strip()
        score = 0.0
        components: Dict[str, Any] = {
            "id": hit.id,
            "source_trace": meta.get("source_trace"),
            "source_family": family,
            "components": {},
        }
        if family in {"licensed_review_dataset", "rap_tabular", "spreadsheet"}:
            score += 5.0
            components["components"]["source_family"] = 5.0
        else:
            components["components"]["source_family"] = 0.0
            _record_breakdown(plan, components, accepted=False)
            continue
        missing = [key for key in REVIEW_REQUIRED_METADATA if not meta.get(key)]
        components["missing_required_metadata"] = missing
        if missing:
            _record_breakdown(plan, components, accepted=False)
            continue
        score += 4.0
        components["components"]["required_metadata"] = 4.0
        searchable = _hit_searchable_text(hit, meta)
        identity_searchable = _hit_identity_text(meta)
        missing_entity_terms = _missing_review_required_entity_terms(
            identity_searchable,
            query,
            entity_hints,
        )
        components["missing_required_entity_terms"] = missing_entity_terms
        if missing_entity_terms:
            _record_breakdown(plan, components, accepted=False)
            continue
        source_name = _canonical_source_name(meta.get("source_name") or meta.get("source_site"))
        if requested_sources:
            if source_name in requested_sources:
                score += 5.0
                components["components"]["requested_source"] = 5.0
            else:
                components["components"]["requested_source"] = 0.0
                components["requested_source_missing_for_hit"] = True
        term_score, matched_group_count = _term_group_score(_review_term_groups(query, entity_hints), hit, meta)
        score += term_score
        components["components"]["entity_terms"] = term_score
        components["matched_term_groups"] = matched_group_count
        if category == "multi_review_compare":
            score += 1.0
            components["components"]["multi_review"] = 1.0
        components["score"] = score
        scored.append((score, hit, components))
        _record_breakdown(plan, components, accepted=True)

    scored.sort(key=lambda item: item[0], reverse=True)
    accepted = [hit for score, hit, _components in scored if score >= 9.0]
    if not accepted:
        missing = ["licensed_review_source"]
        if requested_sources:
            missing.append("requested_review_source")
        return [], _fail(plan, "licensed_review_source_missing", missing)
    if requested_sources:
        accepted_sources = {
            _canonical_source_name(
                normalize_source_metadata(hit.meta or {}).get("source_name")
                or normalize_source_metadata(hit.meta or {}).get("source_site")
            )
            for hit in accepted
        }
        missing_requested = sorted(source for source in requested_sources if source not in accepted_sources)
        if missing_requested:
            plan["status"] = "partial_pass"
            plan["missing_contract_fields"] = sorted(
                set(list(plan.get("missing_contract_fields") or []) + ["requested_review_source"])
            )
            plan["missing_authorized_sources"] = missing_requested
            plan["partial_pass_reason"] = "requested_review_source_missing_but_authorized_alternatives_available"
    plan["answer_plan"] = _build_generic_answer_plan("licensed_review", accepted)
    plan["selected_hit_count_after_contract"] = len(accepted)
    return accepted[:8], plan


def _apply_book_contract(
    *,
    query: str,
    entity_hints: Dict[str, Any],
    selected_hits: Sequence[Hit],
    plan: Dict[str, Any],
) -> Tuple[List[Hit], Dict[str, Any]]:
    term_groups = _book_term_groups(query, entity_hints)
    scored: List[Tuple[float, Hit, Dict[str, Any]]] = []
    for hit in selected_hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        family = str(meta.get("source_family") or "").strip()
        components: Dict[str, Any] = {
            "id": hit.id,
            "source_trace": meta.get("source_trace"),
            "source_family": family,
            "components": {},
        }
        if family not in {"ocr_book_corpus", "book"}:
            components["components"]["source_family"] = 0.0
            _record_breakdown(plan, components, accepted=False)
            continue
        missing = [key for key in BOOK_REQUIRED_METADATA if not meta.get(key)]
        components["missing_required_metadata"] = missing
        if missing:
            _record_breakdown(plan, components, accepted=False)
            continue
        score = 7.0
        components["components"]["source_family"] = 5.0
        components["components"]["required_metadata"] = 2.0
        term_score, matched_group_count = _term_group_score(term_groups, hit, meta)
        score += term_score
        components["components"]["entity_terms"] = term_score
        components["matched_term_groups"] = matched_group_count
        narrative_score = _book_narrative_score(hit, meta)
        score += narrative_score
        components["components"]["narrative_quality"] = narrative_score
        components["score"] = score
        required_group_count = len(term_groups)
        matched_group_count = int(components.get("matched_term_groups") or 0)
        if required_group_count and matched_group_count < required_group_count:
            _record_breakdown(plan, components, accepted=False)
            continue
        scored.append((score, hit, components))
        _record_breakdown(plan, components, accepted=True)

    scored.sort(key=lambda item: item[0], reverse=True)
    accepted = [hit for score, hit, _components in scored if score >= 12.0]
    if not accepted:
        return [], _fail(plan, "book_contract_source_missing", ["book_passage_with_requested_entities"])
    plan["answer_plan"] = _build_generic_answer_plan("book_ocr", accepted)
    plan["selected_hit_count_after_contract"] = len(accepted)
    return accepted[:6], plan


def _apply_customer_facts_contract(
    *,
    selected_hits: Sequence[Hit],
    plan: Dict[str, Any],
) -> Tuple[List[Hit], Dict[str, Any]]:
    accepted: List[Hit] = []
    for hit in selected_hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        components = {
            "id": hit.id,
            "source_trace": meta.get("source_trace"),
            "source_family": meta.get("source_family"),
            "components": {},
        }
        if str(meta.get("source_family") or "").strip() != "customer_facts_pack":
            components["components"]["source_family"] = 0.0
            _record_breakdown(plan, components, accepted=False)
            continue
        missing = [key for key in ("source_name", "source_trace", "allowed_use") if not meta.get(key)]
        if missing:
            components["missing_required_metadata"] = missing
            _record_breakdown(plan, components, accepted=False)
            continue
        components["components"]["source_family"] = 5.0
        components["components"]["required_metadata"] = 3.0
        accepted.append(hit)
        _record_breakdown(plan, components, accepted=True)
    if not accepted:
        return [], _fail(plan, "customer_facts_source_missing", ["customer_facts_pack"])
    plan["answer_plan"] = _build_generic_answer_plan("customer_facts_pack", accepted)
    plan["selected_hit_count_after_contract"] = len(accepted)
    return accepted[:6], plan


def _requested_source_names(query: str) -> List[str]:
    lowered = str(query or "").lower()
    requested: List[str] = []
    for canonical, aliases in SOURCE_NAME_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            requested.append(canonical)
    return requested


def _canonical_source_name(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    lowered = lowered.replace("-", "_")
    for canonical, aliases in SOURCE_NAME_ALIASES.items():
        if lowered == canonical or any(alias in lowered for alias in aliases):
            return canonical
    return lowered


def _review_term_groups(query: str, entity_hints: Dict[str, Any]) -> List[List[str]]:
    groups = _entity_term_groups(query, entity_hints)
    vintage = str(entity_hints.get("vintage") or "").strip()
    if not vintage:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(query or ""))
        vintage = match.group(1) if match else ""
    if vintage:
        groups.append([vintage])
    return groups[:8]


def _missing_review_required_entity_terms(
    searchable: str,
    query: str,
    entity_hints: Dict[str, Any],
) -> List[str]:
    missing: List[str] = []
    required = _review_required_entity_terms(entity_hints, query=query)
    for label, terms in required.items():
        if terms and not all(_term_matches_searchable_text(term, searchable) for term in terms):
            missing.append(label)
    return missing


def _review_required_entity_terms(entity_hints: Dict[str, Any], *, query: str = "") -> Dict[str, List[str]]:
    producer_terms = _terms_from_hint(entity_hints.get("producer"))
    wine_terms = _terms_from_hint(entity_hints.get("wine_name") or entity_hints.get("vineyard"))
    if not wine_terms:
        full_terms = _terms_from_hint(entity_hints.get("full_wine_name"))
        wine_terms = [term for term in full_terms if term not in set(producer_terms)]
    if not wine_terms:
        wine_terms = _wine_terms_from_query(query)
    if wine_terms and producer_terms:
        wine_set = set(wine_terms)
        producer_terms = [term for term in producer_terms if term not in wine_set]
    vintage = str(entity_hints.get("vintage") or "").strip()
    if not vintage:
        match = re.search(r"\b((?:19|20)\d{2})\b", str(query or ""))
        vintage = match.group(1) if match else ""
    return {
        "producer": producer_terms[:4],
        "wine_name": wine_terms[:4],
        "vintage": [vintage] if vintage else [],
    }


def _wine_terms_from_query(query: str) -> List[str]:
    normalized = _normalize_text(query)
    known_patterns = {
        "bonnes-mares": ["bonnes", "mares"],
        "bonnes mares": ["bonnes", "mares"],
        "clos-de-la-roche": ["clos", "roche"],
        "clos de la roche": ["clos", "roche"],
        "clos roche": ["clos", "roche"],
        "clos saint jacques": ["clos", "saint", "jacques"],
        "clos st jacques": ["clos", "saint", "jacques"],
        "clos st. jacques": ["clos", "saint", "jacques"],
        "la tache": ["tache"],
        "richebourg": ["richebourg"],
        "romanee conti": ["romanee", "conti"],
        "chambertin": ["chambertin"],
        "musigny": ["musigny"],
        "montrachet": ["montrachet"],
        "meursault": ["meursault"],
        "volnay": ["volnay"],
    }
    for pattern, terms in known_patterns.items():
        if pattern in normalized:
            return terms
    return []


def _terms_from_hint(value: Any) -> List[str]:
    if value in (None, "", [], {}):
        return []
    values = value if isinstance(value, list) else [value]
    terms: List[str] = []
    for item in values:
        for term in _meaningful_terms(str(item)):
            if term not in terms:
                terms.append(term)
    return terms


def _book_term_groups(query: str, entity_hints: Dict[str, Any]) -> List[List[str]]:
    text = _normalize_text(query)
    groups: List[List[str]] = []
    if "la tache" in text or "la tâche" in text or "tache" in text or "tâche" in text:
        groups.append(["tache", "tâche", "la tache", "la tâche"])
    if "vosne" in text:
        groups.append(["vosne", "vosne-romanee", "vosne romanee", "vosne-romanée", "vosne romanée"])
    if not groups:
        groups = _entity_term_groups(query, entity_hints)
    return _dedupe_groups(groups)[:8]


def _entity_term_groups(query: str, entity_hints: Dict[str, Any]) -> List[List[str]]:
    groups: List[List[str]] = []
    for key in ("producer", "wine_name", "full_wine_name", "vineyard", "region"):
        value = entity_hints.get(key)
        if value in (None, "", [], {}):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            tokens = _meaningful_terms(str(item))
            for token in tokens:
                groups.append([token])
    if not groups:
        for token in _meaningful_terms(query):
            groups.append([token])
    return _dedupe_groups(groups)


def _meaningful_terms(value: str) -> List[str]:
    stop = {
        "find", "show", "all", "what", "does", "about", "within", "include", "review",
        "score", "source", "cite", "book", "corpus", "historical", "importance", "wine",
        "wines", "ys", "the", "and", "for", "from", "with", "using", "exact",
        "compare", "reviews", "reviewer", "issue", "date", "page", "passage", "passages",
        "grand", "premier", "cru",
    }
    tokens: List[str] = []
    for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9'-]+", value or ""):
        cleaned = _normalize_text(token).strip("-'")
        for part in re.split(r"[-'\s]+", cleaned):
            if not part or part in stop or len(part) < 3:
                continue
            if part not in tokens:
                tokens.append(part)
    return tokens[:8]


def _term_group_score(groups: Sequence[Sequence[str]], hit: Hit, meta: Dict[str, Any]) -> Tuple[float, int]:
    searchable = _hit_searchable_text(hit, meta)
    score = 0.0
    matched = 0
    for group in groups or []:
        if any(_term_matches_searchable_text(term, searchable) for term in group):
            matched += 1
            score += 2.0
    # Attach for caller diagnostics without mutating the Hit.
    return score, matched


def _term_matches_searchable_text(term: Any, searchable: str) -> bool:
    normalized = _normalize_text(term)
    if not normalized:
        return False
    variants = {normalized}
    if normalized == "saint":
        variants.update({"st", "st."})
    elif normalized == "st":
        variants.update({"saint", "st."})
    elif normalized.endswith(" saint"):
        variants.add(normalized[:-6] + " st")
    elif " saint " in normalized:
        variants.add(normalized.replace(" saint ", " st "))
    elif normalized.endswith(" st"):
        variants.add(normalized[:-3] + " saint")
    elif " st " in normalized:
        variants.add(normalized.replace(" st ", " saint "))
    return any(variant in searchable for variant in variants)


def _hit_searchable_text(hit: Hit, meta: Dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(value or "")
            for value in (
                hit.text,
                hit.summary,
                meta.get("producer"),
                meta.get("wine_name"),
                meta.get("full_wine_name"),
                meta.get("vineyard"),
                meta.get("region"),
                meta.get("village"),
                meta.get("source_name"),
                meta.get("book_title"),
                meta.get("source_trace"),
            )
        )
    )


def _hit_identity_text(meta: Dict[str, Any]) -> str:
    return _normalize_text(
        " ".join(
            str(value or "")
            for value in (
                meta.get("producer"),
                meta.get("wine_name"),
                meta.get("full_wine_name"),
                meta.get("vineyard"),
                meta.get("vintage"),
                meta.get("region"),
                meta.get("village"),
            )
        )
    )


def _book_narrative_score(hit: Hit, meta: Dict[str, Any]) -> float:
    text = str(hit.text or hit.summary or "")
    normalized = _normalize_text(text)
    score = 0.0
    word_count = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", text))
    if word_count >= 45:
        score += 1.0
    if re.search(r"[.!?。！？]", text):
        score += 1.0
    if any(token in normalized for token in ("history", "historical", "sought", "owned", "market", "1760", "conti", "illustrious", "monopoly")):
        score += 3.0
    numeric_tokens = re.findall(r"\b\d{1,3}\b", text)
    if len(numeric_tokens) > max(word_count // 3, 20) and "." not in text:
        score -= 3.0
    return score


def _hits_have_cerp_proof(hits: Iterable[Hit]) -> bool:
    for hit in hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        if str(meta.get("source_family") or "").strip() == "cerp_snapshot":
            return True
        if str(meta.get("source") or "").strip().lower() == "cerp":
            return True
    return False


def _build_generic_answer_plan(evidence_type: str, hits: Sequence[Hit]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for hit in list(hits or [])[:8]:
        meta = normalize_source_metadata(hit.meta or {})
        items.append(
            {
                "id": hit.id,
                "evidence_type": evidence_type,
                "source_family": meta.get("source_family"),
                "source_name": meta.get("source_name") or meta.get("book_title") or meta.get("filename"),
                "source_trace": meta.get("source_trace"),
                "page": meta.get("page"),
                "row_id": meta.get("row_id"),
                "producer": meta.get("producer"),
                "wine_name": meta.get("wine_name") or meta.get("full_wine_name"),
                "vintage": meta.get("vintage"),
                "score": meta.get("score"),
                "reviewer": meta.get("reviewer"),
                "excerpt": str(hit.summary or hit.text or "")[:900],
            }
        )
    return {
        "items": items,
        "allowed_claims": [
            "Use only facts directly supported by evidence items.",
            "Do not use customer facts for live stock, price, CERP mapping, or review scores.",
        ],
    }


def _build_cerp_answer_plan(cerp_products: Sequence[Dict[str, Any]], hits: Sequence[Hit]) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for product in list(cerp_products or [])[:8]:
        code = str(product.get("no") or product.get("code") or product.get("id") or "").strip()
        items.append(
            {
                "evidence_type": "cerp_snapshot",
                "source_trace": product.get("source_trace") or f"CERP ExportProduct/ExportProductsInfo | sku:{code}",
                "sku": code,
                "stock": product.get("stock") or product.get("stock_qty") or product.get("total_stock"),
                "price": product.get("price") or product.get("list_price"),
                "vip_price": product.get("vip_price"),
                "excerpt": product.get("name") or product.get("name_en") or product.get("name_ch") or code,
            }
        )
    if not items:
        return _build_generic_answer_plan("cerp_snapshot", hits)
    return {
        "items": items,
        "allowed_claims": [
            "Use CERP proof for stock, price, VIP price, sellable status, and SKU facts.",
            "Do not infer cost, margin, sales velocity, allocation, or supplier terms.",
        ],
    }


def _fail(plan: Dict[str, Any], reason: str, missing_fields: Sequence[str]) -> Dict[str, Any]:
    failed = dict(plan)
    failed["status"] = "fail_closed"
    failed["fail_closed_reason"] = reason
    failed["missing_contract_fields"] = list(missing_fields or [])
    flags = list(failed.get("hard_error_flags") or [])
    if reason not in flags:
        flags.append(reason)
    failed["hard_error_flags"] = flags
    failed["selected_hit_count_after_contract"] = 0
    return failed


def _record_breakdown(plan: Dict[str, Any], components: Dict[str, Any], *, accepted: bool) -> None:
    item = dict(components)
    item["accepted"] = accepted
    plan.setdefault("score_breakdown", []).append(item)


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _dedupe_groups(groups: Sequence[Sequence[str]]) -> List[List[str]]:
    deduped: List[List[str]] = []
    seen: set[Tuple[str, ...]] = set()
    for group in groups or []:
        normalized = tuple(sorted({_normalize_text(item) for item in group if str(item or "").strip()}))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(list(normalized))
    return deduped
