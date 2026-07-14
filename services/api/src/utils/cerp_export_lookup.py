import json
import os
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

_EXPORT_FILENAME = "response_20251217T201744_products_export.txt"


def _find_export_path() -> Path:
    env_path = os.getenv("CERP_PRODUCTS_EXPORT_PATH")
    if env_path:
        return Path(env_path)
    current = Path(__file__).resolve().parent
    for _ in range(12):
        candidate = current / _EXPORT_FILENAME
        if candidate.exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _EXPORT_FILENAME


CERP_EXPORT_PATH = _find_export_path()

_NORMALIZE_RE = re.compile(r"[^\w]+", re.UNICODE)
_BARCODE_CLEAN_RE = re.compile(r"[^A-Z0-9]")
_ALIAS_FIELDS = ("invn005", "invn006", "invn077")
_SEARCH_FIELDS = (
    "invn005",
    "invn006",
    "invn077",
    "invn002",
    "invn008",
    "invn030",
    "invn051",
    "invn801",
    "invn804",
    "invn805",
)
_QUERY_NOISE_RE = re.compile(
    r"\b(?:quote|quotation|stock|inventory|list|wine|wines)\b|\u9152\u6b3e|\u5831\u50f9|\u6e05\u55ae|\u63a8\u85a6|\u627e|\u67e5\u8a62",
    re.IGNORECASE,
)


def _normalize_label(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    deaccented = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    deaccented = _QUERY_NOISE_RE.sub(" ", deaccented)
    normalized = _NORMALIZE_RE.sub(" ", deaccented.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_barcode(value: Optional[str]) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = _BARCODE_CLEAN_RE.sub("", value.upper())
    return cleaned.strip()


@lru_cache(maxsize=1)
def _load_export_rows() -> List[Dict[str, Any]]:
    if not CERP_EXPORT_PATH.exists():
        return []
    text = CERP_EXPORT_PATH.read_text(encoding="utf-8", errors="ignore")
    decoder = json.JSONDecoder()
    idx = 0
    rows: List[Dict[str, Any]] = []
    length = len(text)
    while idx < length:
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            obj, end_idx = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        data = obj.get("data") or {}
        rows.extend(data.get("wd4invnas") or [])
        idx = end_idx
    return rows


@lru_cache(maxsize=1)
def _build_alias_index() -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _load_export_rows():
        for field in _ALIAS_FIELDS:
            value = row.get(field)
            normalized = _normalize_label(value)
            if normalized:
                index[normalized].append(row)
    return index


@lru_cache(maxsize=1)
def _build_code_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for row in _load_export_rows():
        code = (row.get("invn002") or "").strip()
        if code:
            index[code.upper()] = row
    return index


@lru_cache(maxsize=1)
def _build_barcode_index() -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for row in _load_export_rows():
        barcode = row.get("invn008")
        normalized = _normalize_barcode(barcode)
        if normalized:
            index[normalized] = row
    return index


@lru_cache(maxsize=1)
def _build_producer_index() -> Dict[str, List[Dict[str, Any]]]:
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _load_export_rows():
        producer = row.get("invn006")
        normalized = _normalize_label(producer)
        if normalized:
            index[normalized].append(row)
    return index


def find_export_row_by_code(code: str) -> Optional[Dict[str, Any]]:
    if not code:
        return None
    return _build_code_index().get(code.strip().upper())


def find_export_row_by_barcode(barcode: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_barcode(barcode)
    if not normalized:
        return None
    return _build_barcode_index().get(normalized)


def find_best_matching_product(name: str) -> Optional[Dict[str, Any]]:
    normalized_query = _normalize_label(name)
    if not normalized_query:
        return None

    alias_index = _build_alias_index()
    if normalized_query in alias_index:
        return alias_index[normalized_query][0]

    query_tokens = set(normalized_query.split())
    if not query_tokens:
        return None

    best_row: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for row in _load_export_rows():
        candidate_name = row.get("invn005") or ""
        normalized_candidate = _normalize_label(candidate_name)
        if not normalized_candidate:
            continue
        if normalized_query == normalized_candidate:
            return row
        candidate_tokens = set(normalized_candidate.split())
        overlap = len(query_tokens & candidate_tokens)
        if overlap == 0:
            continue
        score = overlap
        if normalized_query in normalized_candidate:
            score += 1.0
        length_diff = abs(len(normalized_candidate) - len(normalized_query))
        score -= min(length_diff / 10.0, 1.5)
        if score > best_score:
            best_score = score
            best_row = row

    if best_score >= 2.0:
        return best_row
    return None


def find_best_matching_producer(name: str) -> Optional[str]:
    """
    Return the closest producer name (invn006) using normalized token overlap.
    """
    normalized_query = _normalize_label(name)
    if not normalized_query:
        return None

    producer_index = _build_producer_index()
    if normalized_query in producer_index:
        first = producer_index[normalized_query][0]
        return (first.get("invn006") or "").strip() or None

    query_tokens = set(normalized_query.split())
    if not query_tokens:
        return None

    best_name: Optional[str] = None
    best_score = 0.0
    for raw_name, rows in producer_index.items():
        if not raw_name:
            continue
        tokens = set(raw_name.split())
        overlap = len(tokens & query_tokens)
        if overlap == 0:
            continue
        score = overlap
        if normalized_query in raw_name:
            score += 1.0
        length_diff = abs(len(raw_name) - len(normalized_query))
        score -= min(length_diff / 10.0, 1.5)
        if score > best_score:
            best_score = score
            candidate = rows[0].get("invn006")
            best_name = candidate.strip() if isinstance(candidate, str) else None
    return best_name


def find_products_by_producer(name: str) -> List[Dict[str, Any]]:
    """
    Return all export rows whose producer matches (normalized) the provided name.
    """
    normalized_query = _normalize_label(name)
    if not normalized_query:
        return []
    producer_index = _build_producer_index()
    exact = producer_index.get(normalized_query)
    if exact:
        return exact
    best_name = find_best_matching_producer(name)
    if not best_name:
        return []
    normalized_best = _normalize_label(best_name)
    return producer_index.get(normalized_best, [])


def list_export_producers() -> List[str]:
    producers: List[str] = []
    seen: set[str] = set()
    for row in _load_export_rows():
        producer = str(row.get("invn006") or "").strip()
        normalized = _normalize_label(producer)
        if not producer or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        producers.append(producer)
    return producers


def search_export_rows(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    normalized_query = _normalize_label(query)
    if not normalized_query:
        return []

    tokens = [
        tok
        for tok in normalized_query.split()
        if tok and not (tok.isdigit() and len(tok) < 4)
    ]
    scored: List[tuple[float, Dict[str, Any]]] = []
    for row in _load_export_rows():
        combined_parts = []
        for field in _SEARCH_FIELDS:
            value = row.get(field)
            if not isinstance(value, str):
                continue
            normalized = _normalize_label(value)
            if normalized:
                combined_parts.append(normalized)
        if not combined_parts:
            continue
        combined = " ".join(combined_parts)

        score = 0.0
        if normalized_query and normalized_query in combined:
            score += 3.0
        if tokens:
            matches = sum(1 for tok in tokens if tok in combined)
            if matches == 0:
                continue
            score += float(matches)
        if score > 0:
            scored.append((score, row))

    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[: max(limit, 1)]]
