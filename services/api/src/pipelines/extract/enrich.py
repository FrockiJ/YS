from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Tuple


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def summarize_chunk(text: str, max_sentences: int = 2, max_chars: int = 320) -> str:
    if not text:
        return ""
    normalized = _normalize_whitespace(text)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", normalized) if part.strip()]
    summary = " ".join(sentences[:max_sentences]) if sentences else normalized
    return summary if len(summary) <= max_chars else summary[:max_chars].rstrip() + "..."


def keyword_candidates(text: str, top_n: int = 6) -> List[str]:
    tokens = re.findall(r"[A-Za-z\u4e00-\u9fff]{2,24}", text or "")
    return [word for word, _ in Counter(token.casefold() for token in tokens).most_common(top_n)]


def build_kag_stub(fields: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    for key in ("brand", "product_name", "category", "location", "activity", "specification"):
        raw = fields.get(key)
        values = raw if isinstance(raw, list) else [raw]
        for value in values:
            label = str(value or "").strip()
            if label:
                nodes.append({"id": f"{key}:{label}", "label": label, "type": key})
    for keyword in keywords[:3]:
        nodes.append({"id": f"keyword:{keyword}", "label": keyword, "type": "keyword"})
    return {"nodes": nodes, "edges": edges}


def enrich_chunk(text: str, fields: Dict[str, Any]) -> Tuple[str, List[str], Dict[str, Any]]:
    summary = summarize_chunk(text)
    keywords = keyword_candidates(text)
    return summary, keywords, build_kag_stub(fields or {}, keywords)
