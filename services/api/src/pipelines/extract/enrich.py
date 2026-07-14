from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Tuple


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def summarize_chunk(text: str, max_sentences: int = 2, max_chars: int = 320) -> str:
    """
    Create a short summary so downstream RAG does not need to re-truncate every chunk.
    """
    if not text:
        return ""
    normalized = _normalize_whitespace(text)
    # Split on sentence terminators while keeping multi-lingual punctuation.
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?。！？])\s+", normalized)
        if s.strip()
    ]
    summary = " ".join(sentences[:max_sentences]) if sentences else normalized[:max_chars]
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def keyword_candidates(text: str, top_n: int = 6) -> List[str]:
    if not text:
        return []
    tokens = re.findall(r"[A-Za-z\u4e00-\u9fff]{2,24}", text)
    freq = Counter(tok.lower() for tok in tokens)
    keywords: List[str] = []
    for word, _ in freq.most_common(top_n * 2):
        if all(word != kw.lower() for kw in keywords):
            keywords.append(word)
        if len(keywords) >= top_n:
            break
    return keywords


def build_kag_stub(fields: Dict[str, Any], keywords: List[str]) -> Dict[str, Any]:
    """
    Store a lightweight graph payload so we have a place to persist nodes/edges when KAG lands.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    def _node(node_type: str, label: str) -> Dict[str, Any]:
        return {"id": f"{node_type}:{label}", "label": label, "type": node_type}

    region = fields.get("region")
    village = fields.get("village")
    vineyard = fields.get("vineyard")

    if region:
        nodes.append(_node("region", region))
    if village:
        nodes.append(_node("village", village))
    if vineyard:
        nodes.append(_node("vineyard", vineyard))

    if region and village:
        edges.append({"source": f"region:{region}", "target": f"village:{village}", "relation": "contains"})
    if village and vineyard:
        edges.append({"source": f"village:{village}", "target": f"vineyard:{vineyard}", "relation": "contains"})

    if keywords:
        keyword_nodes = [
            {"id": f"kw:{kw}", "label": kw, "type": "keyword"}
            for kw in keywords[:3]
        ]
        nodes.extend(keyword_nodes)
        for kw_node in keyword_nodes:
            if region:
                edges.append({"source": kw_node["id"], "target": f"region:{region}", "relation": "describes"})

    return {"nodes": nodes, "edges": edges}


def enrich_chunk(text: str, fields: Dict[str, Any]) -> Tuple[str, List[str], Dict[str, Any]]:
    summary = summarize_chunk(text)
    keywords = keyword_candidates(text)
    kag = build_kag_stub(fields or {}, keywords)
    return summary, keywords, kag
