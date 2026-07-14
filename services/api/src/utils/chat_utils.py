import re
import re
from typing import Any, Dict, List, Optional, Set

from .quote_search import normalize_quote_input_text, parse_quote_search_criteria

QUOTE_QUANTITY_PATTERN = re.compile(
    r"(\\d+)\\s*(?:\\u74f6|\\u7bb1|\\u5305|bottles?|bottle|cases?|case|packs?)?",
    flags=re.IGNORECASE,
)


def _sanitize_quote_query(text: str) -> str:
    if not text:
        return ""
    cleaned = normalize_quote_input_text(text)
    cleaned = QUOTE_QUANTITY_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    return cleaned or text.strip()


def _extract_search_keywords(text: str) -> str:
    criteria = parse_quote_search_criteria(text)
    return str(criteria.get("keywords") or "").strip()


def _is_info_intent(text: str) -> bool:
    if not text:
        return False
    return any(
        term in text
        for term in (
            "\\u4ecb\\u7d39",
            "\\u63a8\\u85a6",
            "\\u642d\\u914d",
            "\\u600e\\u9ebc",
            "\\u5982\\u4f55",
            "\\u53ef\\u4ee5\\u55ce",
            "\\u70ba\\u4ec0\\u9ebc",
        )
    )

HIGHLIGHT_MIN = 4
HIGHLIGHT_MAX = 5
SUMMARY_CHAR_LIMIT = 20
LACK_SOURCE_THRESHOLD = 3
LINE_CLEAN_RE = re.compile(r'^[\s\-‧·‧\d\.、、:：()\[\]]+')
MAX_CONTEXT_HITS = 8
PRODUCT_CODE_PATTERN = re.compile(r'\b[A-Z]{2,3}-[A-Z0-9-]{6,}\b')
BARCODE_PATTERN = re.compile(r'\b\d{11,13}\b')
CODE_LABEL_PATTERN = re.compile(r'(?:barcode|no|編號|品號|條碼)\s*[:：]\s*([A-Z0-9-]{3,})', re.IGNORECASE)
INLINE_BARCODE_PATTERN = re.compile(r'barcode\s*[:：]?\s*([A-Z0-9-]{6,})', re.IGNORECASE)
NAME_LABEL_PATTERN = re.compile(r'(?:酒名|品名|name|product name|wine|wine name)\s*[:：]\s*(.+)', re.IGNORECASE)
TERM_TOKEN_RE = re.compile(r'[\w一-鿿]+', re.UNICODE)
SENTENCE_RE = re.compile(r'[^。\uff0e\.!！?？]+[。\uff0e\.!！?？]?')


def _normalize_highlight_line(value: str) -> str:
    if not value:
        return ''
    return LINE_CLEAN_RE.sub('', value).strip()


def _split_sentences(blob: str) -> List[str]:
    if not blob:
        return []
    sanitized = blob.replace('\r', '\n').strip()
    if not sanitized:
        return []
    collapsed_newlines = re.sub(r'\n+', '\n', sanitized)
    normalized_whitespace = re.sub(r'[ \t]+', ' ', collapsed_newlines)
    chunks = [chunk for chunk in SENTENCE_RE.findall(normalized_whitespace) if chunk.strip()]
    if not chunks and '\n' in normalized_whitespace:
        chunks = [part for part in normalized_whitespace.split('\n') if part.strip()]
    if not chunks:
        chunks = [normalized_whitespace]
    results: List[str] = []
    for chunk in chunks:
        normalized_chunk = _normalize_highlight_line(chunk)
        if normalized_chunk:
            results.append(normalized_chunk)
    return results

def _split_fragments(blob: str) -> List[str]:
    if not blob:
        return []
    chunks = re.split(r'[,，、；;]\s*', blob)
    results: List[str] = []
    for chunk in chunks:
        normalized = _normalize_highlight_line(chunk)
        if normalized:
            results.append(normalized)
    return results


def _split_summary_lines(blob: str) -> List[str]:
    if not blob:
        return []
    lines = re.split(r'[\r\n]+', blob)
    return [line.strip() for line in lines if line and line.strip()]

def _build_highlights(answer_text: str, summary_text: str, keywords: List[str]) -> List[str]:
    highlights: List[str] = []
    seen = set()

    def push(value: str):
        normalized = _normalize_highlight_line(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        highlights.append(normalized)

    answer_text = (answer_text or '').strip()
    summary_text = (summary_text or '').strip()
    keyword_candidates = keywords or []

    if answer_text:
        for sentence in _split_sentences(answer_text):
            push(sentence)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]
        for fragment in _split_fragments(answer_text):
            push(fragment)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN:
        for kw in keyword_candidates:
            push(f'關鍵字: {kw}')
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN and not answer_text and summary_text:
        for line in _split_summary_lines(summary_text):
            push(line)
            if len(highlights) >= HIGHLIGHT_MAX:
                return highlights[:HIGHLIGHT_MAX]

    if len(highlights) < HIGHLIGHT_MIN and answer_text:
        push(answer_text)

    return highlights[:HIGHLIGHT_MAX]


def _clip_summary_text(value: str) -> str:
    normalized = ' '.join((value or '').split())
    if not normalized:
        return ''
    if len(normalized) <= SUMMARY_CHAR_LIMIT:
        return normalized
    return normalized[:SUMMARY_CHAR_LIMIT].rstrip() + '...'


def _build_compact_summary(summary_text: str, answer_text: str) -> str:
    """
    Prefer the RAG summary if available; otherwise take the first sentence of the
    assistant answer so the front-end summary chip stays aligned with the reply.
    """
    summary_text = (summary_text or '').strip()
    answer_text = (answer_text or '').strip()
    candidates: List[str] = []
    if summary_text:
        candidates.extend(_split_summary_lines(summary_text))
    if not candidates and answer_text:
        candidates.extend(_split_sentences(answer_text))
    for candidate in candidates:
        clipped = _clip_summary_text(candidate)
        if clipped:
            return clipped
    return ''


def _tokenize_for_search(value: str) -> List[str]:
    if not value:
        return []
    return [match.group(0).lower() for match in TERM_TOKEN_RE.finditer(value)]


def _collect_relevance_terms(
    text: str,
    query_variants: List[str],
    alias_filters: Dict[str, str],
) -> List[str]:
    terms = set()
    sources = [text] + (query_variants or [])
    for source in sources:
        terms.update(_tokenize_for_search(str(source)))
    for alias_value in (alias_filters or {}).values():
        terms.update(_tokenize_for_search(str(alias_value)))
    return [term for term in terms if term]


def _meta_to_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, dict):
        parts = [_meta_to_text(v) for v in value.values()]
        return ' '.join(part for part in parts if part)
    if isinstance(value, (list, tuple, set)):
        parts = [_meta_to_text(v) for v in value]
        return ' '.join(part for part in parts if part)
    return str(value)


def _collect_hit_text(hit: Dict[str, Any]) -> str:
    parts = []
    for key in ('summary', 'text'):
        val = hit.get(key)
        if isinstance(val, str):
            parts.append(val)
    parts.append(_meta_to_text(hit.get('meta')))
    keywords = hit.get('keywords')
    if isinstance(keywords, (list, tuple, set)):
        parts.extend(str(k) for k in keywords if k)
    return ' '.join(part for part in parts if part)


def _hit_matches_terms(hit: Dict[str, Any], terms: List[str]) -> bool:
    if not terms:
        return False
    haystack = _collect_hit_text(hit).lower()
    if not haystack:
        return False
    return any(term in haystack for term in terms)


def _hit_score(hit: Dict[str, Any]) -> float:
    score = hit.get('score')
    try:
        return float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _select_relevant_hits(
    hits: List[Dict[str, Any]],
    terms: List[str],
    max_hits: int = MAX_CONTEXT_HITS,
) -> List[Dict[str, Any]]:
    if not hits:
        return []
    if not terms:
        return sorted(hits, key=_hit_score, reverse=True)[:max_hits]
    matched = [hit for hit in hits if _hit_matches_terms(hit, terms)]
    if matched:
        return sorted(matched, key=_hit_score, reverse=True)[:max_hits]
    # If nothing matched (e.g., follow-up like "查庫存"), keep the best available hits to preserve context
    return sorted(hits, key=_hit_score, reverse=True)[:max_hits]


def _safe_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _ensure_meta_dict(fragment: Any) -> Dict[str, Any]:
    if isinstance(fragment, dict):
        return fragment
    if isinstance(fragment, str):
        try:
            parsed = json.loads(fragment)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _normalize_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float):
            if value.is_integer():
                value = int(value)
        return str(value).strip()
    text = str(value).strip()
    return text or None


def _extract_filename(meta: Dict[str, Any]) -> Optional[str]:
    for key in ("filename", "file", "title", "name", "document"):
        candidate = meta.get(key)
        if isinstance(candidate, str):
            candidate = candidate.strip()
            if candidate:
                return candidate
    return None


def _build_identity(record: Dict[str, Any]) -> Dict[str, Optional[str]]:
    meta = _ensure_meta_dict(record.get("meta"))
    return {
        "id": _normalize_identifier(record.get("id")),
        "document_id": _normalize_identifier(record.get("document_id")),
        "chunk_idx": _normalize_identifier(record.get("chunk_idx")),
        "filename": _normalize_identifier(
            record.get("filename") or _extract_filename(meta)
        ),
    }


def _collect_keyword_hints_from_hits(hits: List[Dict[str, Any]], limit: int = 12) -> List[str]:
    hints: List[str] = []
    for hit in hits or []:
        for kw in hit.get("keywords") or []:
            if not kw:
                continue
            if kw in hints:
                continue
            hints.append(kw)
            if len(hints) >= limit:
                return hints
    return hints


def _extract_terms_from_value(value: Any) -> Set[str]:
    terms: Set[str] = set()
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            terms.add(normalized)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            terms.update(_extract_terms_from_value(item))
    elif isinstance(value, dict):
        for item in value.values():
            terms.update(_extract_terms_from_value(item))
    return terms


def _detect_portfolio_focus(
    text: str,
    intent_name: Optional[str],
    alias_filters: Dict[str, Any],
    preferred_brands: Optional[List[str]],
) -> bool:
    normalized_intent = (intent_name or "").strip().upper()
    if normalized_intent and normalized_intent != "FREE_CHAT":
        return True
    lowered_text = (text or "").lower()
    preferred_terms: Set[str] = set()
    for brand in preferred_brands or []:
        if isinstance(brand, str):
            candidate = brand.strip().lower()
            if candidate:
                preferred_terms.add(candidate)
    alias_terms: Set[str] = set()
    for value in alias_filters.values():
        alias_terms.update(_extract_terms_from_value(value))
    for term in preferred_terms.union(alias_terms):
        if term and term in lowered_text:
            return True
    return False


def _identity_matches_token(identity: Dict[str, Optional[str]], token: Dict[str, Optional[str]]) -> bool:
    if not identity or not token:
        return False
    if token.get("id") and token["id"] == identity.get("id"):
        return True
    if token.get("document_id") and token["document_id"] == identity.get("document_id"):
        if token.get("chunk_idx") and token["chunk_idx"] == identity.get("chunk_idx"):
            return True
        if not token.get("chunk_idx"):
            return True
    if token.get("filename") and token["filename"] == identity.get("filename"):
        return True
    return False


def _filter_hits_by_citations(
    hits: List[Dict[str, Any]], citations: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not hits or not citations:
        return hits
    citation_tokens: List[Dict[str, Optional[str]]] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        meta = _ensure_meta_dict(citation.get("meta"))
        identity = {
            "id": _normalize_identifier(citation.get("id")),
            "document_id": _normalize_identifier(citation.get("document_id")),
            "chunk_idx": _normalize_identifier(citation.get("chunk_idx")),
            "filename": _normalize_identifier(
                citation.get("filename") or _extract_filename(meta)
            ),
        }
        if any(identity.values()):
            citation_tokens.append(identity)
    if not citation_tokens:
        return hits

    matched: List[Dict[str, Any]] = []
    seen_keys = set()

    for hit in hits:
        identity = _build_identity(hit)
        if any(_identity_matches_token(identity, token) for token in citation_tokens):
            key = (
                identity["id"],
                identity["document_id"],
                identity["chunk_idx"],
                identity["filename"],
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matched.append(hit)
    return matched or hits


def _filter_citations_by_hits(
    citations: List[Dict[str, Any]], hits: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not citations or not hits:
        return citations or []
    hit_identities = [_build_identity(hit) for hit in hits]
    filtered: List[Dict[str, Any]] = []
    seen_keys = set()
    for citation in citations:
        identity = _build_identity(citation)
        if not identity:
            continue
        if not any(_identity_matches_token(hit_identity, identity) for hit_identity in hit_identities):
            continue
        key = (
            identity["id"],
            identity["document_id"],
            identity["chunk_idx"],
            identity["filename"],
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        filtered.append(citation)
    return filtered or citations


def _first_alias_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                return entry.strip()
    return None


def _extract_product_name_candidate(text: str) -> Optional[str]:
    if not text:
        return None
    match = NAME_LABEL_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_inline_barcode(text: str) -> Optional[str]:
    if not text:
        return None
    match = INLINE_BARCODE_PATTERN.search(text)
    if not match:
        return None
    return match.group(1).strip().upper()


def _collect_search_candidates(
    text: str,
    alias_filters: Dict[str, Any],
    query_variants: List[str],
) -> List[str]:
    candidates: List[str] = []
    explicit = _extract_product_name_candidate(text)
    if explicit:
        candidates.append(explicit)
    for variant in query_variants or []:
        normalized = (variant or "").strip()
        if normalized:
            candidates.append(normalized)
    for value in alias_filters.values():
        alias_value = _first_alias_value(value)
        if alias_value:
            candidates.append(alias_value.strip())
    normalized_text = (text or "").strip()
    if normalized_text:
        candidates.append(normalized_text)
    seen = set()
    deduped: List[str] = []
    for cand in candidates:
        lowered = cand.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(cand)
    return deduped

def _format_top_stock_answer(products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    if not products:
        return "目前無法取得庫存資料。"
    lines = []
    for idx, product in enumerate(products, 1):
        parts = [f"{idx}. {product.get('name') or product.get('no') or '未命名'}"]
        if product.get("no"):
            parts.append(f"[{product['no']}]")
        if product.get("producer"):
            parts.append(f"({product['producer']})")
        if product.get("stock") is not None:
            parts.append(f"庫存 {int(product['stock'])}")
        if product.get("price"):
            try:
                price_val = float(product["price"])
                parts.append(f"單價 ${price_val:,.0f}")
            except (TypeError, ValueError):
                pass
        lines.append(" ".join(parts))
    header = "庫存最高的商品：" if lang.startswith("zh") else "Top products by stock:"
    return header + "\n" + "\n".join(lines)


def _format_producer_top_stock_answer(producer: str, products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    if not products:
        return f"{producer} 目前查無庫存商品。"
    header = f"{producer} 庫存最高的商品：" if lang.startswith("zh") else f"Top stock for {producer}:"
    lines = []
    for idx, product in enumerate(products, 1):
        name = product.get("name") or product.get("no") or "未命名"
        vintage = product.get("vintage") or "-"
        stock = product.get("stock")
        parts = [f"{idx}. {name}", f"年份 {vintage}"]
        if stock is not None:
            parts.append(f"庫存 {int(stock)}")
        lines.append(" / ".join(parts))
    return header + "\n" + "\n".join(lines)


def _format_producer_profile_answer(
    producer: str,
    products: List[Dict[str, Any]],
    lang: str = "zh-Hant",
    limit: int = 4,
) -> str:
    """
    Quick fallback summary when asking about a producer but RAG hits are empty.
    """
    if not products:
        return f"{producer} 目前暫無相關庫存或資料。"
    heading = f"{producer} 現有產品：" if lang.startswith("zh") else f"{producer} current portfolio:"
    sorted_products = sorted(products, key=lambda p: _safe_int(p.get("stock")), reverse=True)
    lines = []
    for idx, product in enumerate(sorted_products[:limit], 1):
        name = product.get("name") or product.get("no") or "未命名"
        vintage = product.get("vintage") or "-"
        stock = _safe_int(product.get("stock"))
        lines.append(f"{idx}. {name} / {vintage}（庫存 {stock}）")
    tail = "如需甜型或特定口味，請告訴我風格或預算，我再精選。" if lang.startswith("zh") else "Tell me style/budget if you want sweeter picks."
    return heading + "\n" + "\n".join(lines) + "\n" + tail


def _format_out_of_stock_notice(producer: Optional[str], products: List[Dict[str, Any]], lang: str = "zh-Hant") -> str:
    """
    When no stock but have product info, list them and ask to pivot.
    """
    if lang.startswith("zh"):
        header = f"{producer} 目前無庫存的產品：" if producer else "目前無庫存的產品："
        pivot = "要改推薦其他有庫存的類似產品嗎？或允許我查網路的資訊？"
    else:
        header = f"{producer} has no stock; here are the products:" if producer else "No stock found; here are the products:"
        pivot = "Do you want suggestions for similar in-stock products or let me search the web?"
    lines = []
    for idx, product in enumerate(products, 1):
        name = product.get("name") or product.get("no") or "Unnamed"
        vintage = product.get("vintage") or "-"
        lines.append(f"{idx}. {name} / {vintage}（庫存 0）")
    return header + "\n" + "\n".join(lines) + "\n" + pivot

