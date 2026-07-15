from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional

from ...core import db
from ...pipelines.rag.searcher import rag_corpus_status, vector_search
from ...schemas.ai import Hit, RetrievalResult
from .external_search import ExternalSearchService


class RetrievalService:
    """Knowledge-first retrieval: qualified RAG first, external only when required."""

    def __init__(self, external_search_service: Optional[Any] = None, **_: Any) -> None:
        self._external_search_service = external_search_service or ExternalSearchService()

    async def search(
        self,
        query: str,
        *,
        conn=None,
        rag_k: int = 20,
        query_variants: Optional[List[str]] = None,
        needs_authoritative_sources: bool = False,
        source_policy: str = "internal_preferred",
        external_search_reason: Optional[str] = None,
        prompt_category: Optional[str] = None,
        entity_hints: Optional[Dict[str, Any]] = None,
        request_deadline_at: Optional[float] = None,
        **_: Any,
    ) -> RetrievalResult:
        del prompt_category
        errors: Dict[str, str] = {}
        owned_conn = None
        active_conn = conn
        if active_conn is None:
            owned_conn = await db.get_conn()
            active_conn = owned_conn
        try:
            corpus = await rag_corpus_status(active_conn)
            rag_status = str(corpus.get("status") or "error")
            raw_hits: List[Dict[str, Any]] = []
            if rag_status == "ready":
                try:
                    raw_hits = await self._search_variants(
                        active_conn,
                        query,
                        query_variants=query_variants,
                        rag_k=max(1, min(int(rag_k or 20), 20)),
                    )
                except Exception as exc:
                    rag_status = "error"
                    errors["rag"] = f"{type(exc).__name__}: {exc}"
            elif rag_status == "error":
                errors["rag"] = str(corpus.get("error") or "RAG corpus validation failed")
            if rag_status == "ready" and not raw_hits:
                rag_status = "no_relevant_hits"
            if rag_status == "ready" and raw_hits:
                rag_status = "used"

            internal_hits = [self._to_hit(item) for item in raw_hits[:6]]
            external_hits: List[Hit] = []
            external_errors: Dict[str, str] = {}
            external_info = self._external_info_not_attempted(external_search_reason)
            should_attempt_external = bool(
                needs_authoritative_sources
                or str(source_policy or "").strip() == "authoritative_external_required"
                or external_search_reason
            )
            if should_attempt_external:
                try:
                    search_result = await asyncio.to_thread(
                        self._external_search_service.search,
                        query,
                        entity_hints=entity_hints or {},
                        prompt_category="source_validation",
                        external_search_reason=external_search_reason or "authoritative_required",
                        source_policy="authoritative_external_required",
                        needs_authoritative_sources=True,
                        internal_hit_count=len(internal_hits),
                        limit=5,
                        request_deadline_at=request_deadline_at,
                    )
                    external_hits, external_errors, external_info = search_result
                except Exception as exc:
                    external_errors = {"external": f"{type(exc).__name__}: {exc}"}
                    external_info = {
                        **self._external_info_not_attempted(external_search_reason),
                        "attempted": True,
                        "provider_unavailable": True,
                        "termination_reason": "provider_error",
                    }
            errors.update(external_errors or {})

            selected_hits = self._dedupe_hits([*internal_hits, *external_hits])[:6]
            source_tiers = {
                str(hit.id or index): str(hit.source_tier or "internal")
                for index, hit in enumerate(selected_hits)
            }
            snapshot = {
                "query": query,
                "effective_query": query,
                "source_policy": source_policy,
                "response_mode": "generated",
                "rag_status": rag_status,
                "rag_hit_count": len(internal_hits),
                "selected_hit_count": len(selected_hits),
                "internal_hit_count": len(internal_hits),
                "external_hit_count": len(external_hits),
                "external_search": external_info,
                "rag_corpus": corpus,
                "retrieval_errors": errors,
            }
            return RetrievalResult(
                hits=selected_hits,
                cerp_products=[],
                errors=errors,
                internal_hits=internal_hits,
                external_hits=external_hits,
                selected_hits=selected_hits,
                retrieval_errors=errors,
                source_tiers=source_tiers,
                external_search=external_info,
                retrieval_snapshot=snapshot,
            )
        finally:
            if owned_conn is not None:
                await owned_conn.close()

    async def _run_rag_search(
        self,
        query: str,
        *,
        query_variants: Optional[List[str]] = None,
        rag_k: int = 20,
        **_: Any,
    ) -> List[Dict[str, Any]]:
        conn = await db.get_conn()
        try:
            corpus = await rag_corpus_status(conn)
            if corpus.get("status") != "ready":
                return []
            return await self._search_variants(
                conn,
                query,
                query_variants=query_variants,
                rag_k=max(1, min(int(rag_k or 20), 20)),
            )
        finally:
            await conn.close()

    async def _search_variants(
        self,
        conn,
        query: str,
        *,
        query_variants: Optional[List[str]],
        rag_k: int,
    ) -> List[Dict[str, Any]]:
        variants = self._normalize_variants(query, query_variants)
        combined: List[Dict[str, Any]] = []
        for variant in variants[:3]:
            rows = await vector_search(conn, variant, k=rag_k)
            for row in rows:
                item = dict(row)
                item.setdefault("query_variant", variant)
                combined.append(item)
        deduped: Dict[str, Dict[str, Any]] = {}
        for item in combined:
            key = str(item.get("id") or f"{item.get('document_id')}:{item.get('chunk_idx')}")
            current = deduped.get(key)
            if current is None or self._score(item) > self._score(current):
                deduped[key] = item
        return sorted(deduped.values(), key=self._score, reverse=True)[:rag_k]

    @staticmethod
    def _normalize_variants(query: str, variants: Optional[List[str]]) -> List[str]:
        result: List[str] = []
        seen = set()
        for value in [query, *(variants or [])]:
            normalized = str(value or "").strip()
            folded = normalized.casefold()
            if not normalized or folded in seen:
                continue
            seen.add(folded)
            result.append(normalized)
        return result or [str(query or "").strip()]

    @staticmethod
    def _score(item: Dict[str, Any]) -> float:
        try:
            return float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _to_hit(item: Dict[str, Any]) -> Hit:
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        return Hit(
            id=str(item.get("id")) if item.get("id") is not None else None,
            document_id=item.get("document_id"),
            chunk_idx=item.get("chunk_idx"),
            text=str(item.get("text") or ""),
            summary=str(item.get("summary") or ""),
            keywords=list(item.get("keywords") or []),
            meta=meta,
            kg=item.get("kg"),
            score=RetrievalService._score(item),
            query_variant=str(item.get("query_variant") or "") or None,
            source_type=str(meta.get("source_family") or "rag"),
            source_tier=str(meta.get("source_tier") or "internal"),
        )

    @staticmethod
    def _dedupe_hits(hits: Iterable[Hit]) -> List[Hit]:
        result: List[Hit] = []
        seen = set()
        for hit in hits:
            key = str(hit.id or f"{hit.document_id}:{hit.chunk_idx}:{hit.text[:80]}")
            if key in seen:
                continue
            seen.add(key)
            result.append(hit)
        return result

    @staticmethod
    def _external_info_not_attempted(reason: Optional[str]) -> Dict[str, Any]:
        return {
            "attempted": False,
            "reason": reason,
            "provider": None,
            "provider_unavailable": False,
            "termination_reason": "not_required",
            "hit_count_post_filter": 0,
            "authoritative_hit_count": 0,
            "sources": [],
        }
