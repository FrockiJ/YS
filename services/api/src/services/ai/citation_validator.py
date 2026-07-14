from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from ...schemas.ai import Hit


SOURCE_PRIORITY = {
    "cerp": 0,
    "cerp_snapshot": 0,
    "internal_primary": 0,
    "internal_official": 1,
    "official_site": 1,
    "current_official": 1,
    "current_importer": 1,
    "licensed_review_dataset": 2,
    "rap_tabular": 2,
    "ocr_book_corpus": 3,
    "book": 3,
    "spreadsheet": 2,
    "customer_facts_pack": 4,
    "external_evidence": 5,
    "external": 6,
    "open_internet": 6,
    "internal": 7,
}

REVIEW_REQUIRED_METADATA = {
    "producer",
    "wine_name",
    "vintage",
    "source_name",
    "reviewer",
    "score",
}
REVIEW_PROMPT_CATEGORIES = {
    "source_validation",
    "exact_review_lookup",
    "multi_review_compare",
}
BOOK_PROMPT_CATEGORIES = {"book_corpus_lookup", "internal_rag_only_validation"}
SOURCE_HIERARCHY_PROMPT_CATEGORIES = {"source_hierarchy_conflict"}
AUDIT_ANY_OF = (
    "source_trace",
    "page",
    "row_id",
    "record_key",
    "page_url",
    "url",
    "source_url",
    "code",
    "endpoint",
)


def normalize_source_metadata(meta: Dict[str, Any] | None) -> Dict[str, Any]:
    normalized = dict(meta or {})
    source_family = str(normalized.get("source_family") or "").strip()
    source = str(normalized.get("source") or "").strip().lower()
    source_tier = str(normalized.get("source_tier") or "").strip()
    if source == "cerp":
        source_family = source_family or "cerp_snapshot"
        source_tier = source_tier or "internal_primary"
        normalized.setdefault("endpoint", normalized.get("endpoint") or "CERP ExportProduct/ExportProductsInfo")
    elif source_family in {"rap_tabular", "licensed_review_dataset"}:
        normalized.setdefault("doc_type", "source_note")
        source_tier = source_tier or "internal_approved"
        normalized.setdefault("source_family", "licensed_review_dataset")
    elif source_family == "spreadsheet":
        normalized.setdefault("doc_type", "source_note")
        normalized.setdefault("source_family", "licensed_review_dataset")
    elif source_family == "customer_facts_pack":
        normalized.setdefault("doc_type", "customer_fact")
        normalized.setdefault("source_name", "Customer-provided facts pack")
    elif str(normalized.get("doc_type") or "").lower() in {"book", "ocr_book", "reference_book"}:
        normalized.setdefault("source_family", "ocr_book_corpus")
    if not source_family and normalized.get("row_id"):
        source_family = "spreadsheet"
    if not source_family:
        source_family = str(normalized.get("source_group") or normalized.get("source_type") or "internal").strip()
    normalized["source_family"] = source_family
    if source_tier:
        normalized["source_tier"] = source_tier
    normalized.setdefault("source_trace", build_source_trace(normalized))
    return normalized


def build_source_trace(meta: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("source_family", "source_name", "title", "filename", "sheet_name"):
        value = meta.get(key)
        if value:
            parts.append(str(value))
    location = []
    for key, label in (("page", "page"), ("row_id", "row"), ("row_number", "row"), ("chunk_idx", "chunk"), ("code", "sku")):
        value = meta.get(key)
        if value not in (None, ""):
            location.append(f"{label}:{value}")
    if location:
        parts.append(" ".join(location))
    url = meta.get("page_url") or meta.get("url") or meta.get("source_url")
    if url:
        parts.append(str(url))
    return " | ".join(parts)


def validate_hits(
    hits: Iterable[Hit],
    *,
    source_policy: Optional[str] = None,
    prompt_category: Optional[str] = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    unmapped = 0
    missing_required = 0
    for hit in hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        source_family = str(meta.get("source_family") or hit.source_type or "").strip()
        auditable = any(meta.get(key) not in (None, "", [], {}) for key in AUDIT_ANY_OF)
        required_missing: List[str] = []
        if source_family in {"licensed_review_dataset", "rap_tabular"} or prompt_category in REVIEW_PROMPT_CATEGORIES:
            required_missing = [key for key in REVIEW_REQUIRED_METADATA if not meta.get(key)]
        if prompt_category in BOOK_PROMPT_CATEGORIES and source_family in {"ocr_book_corpus", "book"}:
            required_missing = [key for key in ("source_name", "page") if not meta.get(key)]
        if not auditable:
            unmapped += 1
        if required_missing:
            missing_required += 1
        rows.append(
            {
                "id": hit.id,
                "source_family": source_family,
                "source_tier": hit.source_tier or meta.get("source_tier"),
                "auditable": auditable,
                "source_trace": meta.get("source_trace") or build_source_trace(meta),
                "missing_required_metadata": required_missing,
            }
        )
    hard_flags: List[str] = []
    if unmapped:
        hard_flags.append("unmapped_citations")
    if missing_required:
        hard_flags.append("missing_required_source_metadata")
    if source_policy == "authoritative_external_required" and not rows:
        hard_flags.append("authoritative_sources_missing")
    return {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "citation_count": len(rows),
        "unmapped_citation_count": unmapped,
        "missing_required_metadata_count": missing_required,
        "hard_error_flags": hard_flags,
        "items": rows[:12],
    }


def controlling_source(hits: Iterable[Hit]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for hit in hits or []:
        meta = normalize_source_metadata(hit.meta or {})
        candidates.append(
            {
                "id": hit.id,
                "source_family": meta.get("source_family") or hit.source_type,
                "source_tier": hit.source_tier or meta.get("source_tier"),
                "source_name": meta.get("source_name") or meta.get("title") or meta.get("filename"),
                "source_trace": meta.get("source_trace") or build_source_trace(meta),
                "priority": source_priority(meta, hit.source_type, hit.source_tier),
            }
        )
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: (
            int(item["priority"]) if item.get("priority") is not None else 99,
            str(item.get("source_trace") or ""),
        )
    )
    winner = dict(candidates[0])
    winner["conflict_policy"] = (
        "CERP/current internal data > current official/importer > licensed reviews > "
        "books/OCR > customer facts pack > open internet"
    )
    return winner


def should_fail_closed_for_citations(
    validation: Dict[str, Any],
    *,
    source_policy: Optional[str] = None,
    prompt_category: Optional[str] = None,
) -> bool:
    category = str(prompt_category or "")
    policy = str(source_policy or "")
    if validation.get("unmapped_citation_count"):
        return True
    citation_count = int(validation.get("citation_count") or 0)
    missing_required_count = int(validation.get("missing_required_metadata_count") or 0)
    if (
        category == "internal_rag_only_validation"
        and citation_count > 0
        and missing_required_count < citation_count
    ):
        return False
    if missing_required_count and category in REVIEW_PROMPT_CATEGORIES | BOOK_PROMPT_CATEGORIES:
        return True
    if policy == "authoritative_external_required" and not validation.get("citation_count"):
        return True
    if category in REVIEW_PROMPT_CATEGORIES | BOOK_PROMPT_CATEGORIES and not validation.get("citation_count"):
        return True
    if category in SOURCE_HIERARCHY_PROMPT_CATEGORIES and not validation.get("citation_count"):
        return False
    return False


def source_priority(meta: Dict[str, Any] | None, source_type: Optional[str] = None, source_tier: Optional[str] = None) -> int:
    meta = normalize_source_metadata(meta or {})
    candidates = [
        str(source_type or "").strip(),
        str(source_tier or "").strip(),
        str(meta.get("source") or "").strip(),
        str(meta.get("source_tier") or "").strip(),
        str(meta.get("source_family") or "").strip(),
    ]
    for candidate in candidates:
        if candidate in SOURCE_PRIORITY:
            return SOURCE_PRIORITY[candidate]
    return SOURCE_PRIORITY["internal"]
