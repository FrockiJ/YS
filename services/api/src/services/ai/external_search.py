from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from ...schemas.ai import Hit


class ExternalSearchService:
    """Small, domain-neutral external fact lookup used only when verification is required."""

    def __init__(self) -> None:
        self._enabled = os.getenv("EXTERNAL_SEARCH_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        self._provider = os.getenv("EXTERNAL_SEARCH_PROVIDER", "google_cse").strip().lower()
        self._google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self._google_cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        self._timeout = max(1.0, min(float(os.getenv("EXTERNAL_SEARCH_TIMEOUT_SECONDS", "10") or 10), 30.0))

    @staticmethod
    def should_search(
        *,
        source_policy: str,
        needs_authoritative_sources: bool,
        external_search_reason: Optional[str],
        **_: Any,
    ) -> bool:
        return bool(
            needs_authoritative_sources
            or external_search_reason
            or str(source_policy or "").strip() == "authoritative_external_required"
        )

    def search(
        self,
        query: str,
        *,
        source_policy: str = "internal_preferred",
        needs_authoritative_sources: bool = False,
        external_search_reason: Optional[str] = None,
        limit: int = 5,
        **_: Any,
    ) -> Tuple[List[Hit], Dict[str, str], Dict[str, Any]]:
        should_search = self.should_search(
            source_policy=source_policy,
            needs_authoritative_sources=needs_authoritative_sources,
            external_search_reason=external_search_reason,
        )
        info: Dict[str, Any] = {
            "attempted": False,
            "reason": external_search_reason,
            "provider": self._provider or None,
            "query": str(query or "").strip(),
            "provider_unavailable": False,
            "termination_reason": "not_required",
            "hit_count_pre_filter": 0,
            "hit_count_post_filter": 0,
            "authoritative_hit_count": 0,
            "sources": [],
        }
        if not should_search:
            return [], {}, info

        info["attempted"] = True
        if not self._enabled:
            info.update(provider_unavailable=True, termination_reason="provider_disabled")
            return [], {"external": "external_search_disabled"}, info
        if self._provider != "google_cse":
            info.update(provider_unavailable=True, termination_reason="unsupported_provider")
            return [], {"external": "unsupported_external_search_provider"}, info
        if not self._google_api_key or not self._google_cse_id:
            info.update(provider_unavailable=True, termination_reason="provider_not_configured")
            return [], {"external": "google_cse_not_configured"}, info

        params = urllib.parse.urlencode(
            {
                "key": self._google_api_key,
                "cx": self._google_cse_id,
                "q": str(query or "").strip(),
                "num": max(1, min(int(limit or 5), 10)),
            }
        )
        request = urllib.request.Request(
            f"https://www.googleapis.com/customsearch/v1?{params}",
            headers={"Accept": "application/json", "User-Agent": "YS-Knowledge-First/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            info.update(provider_unavailable=True, termination_reason="provider_error")
            return [], {"external": f"{type(exc).__name__}: {exc}"}, info

        items = payload.get("items") if isinstance(payload, dict) else []
        info["hit_count_pre_filter"] = len(items or [])
        hits: List[Hit] = []
        sources: List[Dict[str, str]] = []
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not url or not snippet:
                continue
            domain = (urlparse(url).hostname or "").lower()
            meta = {
                "title": title,
                "url": url,
                "domain": domain,
                "source_family": "external_search",
                "source_tier": "external_evidence",
            }
            hits.append(
                Hit(
                    id=f"external:{index}:{url}",
                    text=snippet,
                    summary=snippet,
                    meta=meta,
                    score=1.0,
                    source_type="external_search",
                    source_tier="external_evidence",
                )
            )
            sources.append({"title": title, "url": url, "domain": domain})
        info.update(
            hit_count_post_filter=len(hits),
            authoritative_hit_count=len(hits),
            sources=sources,
            termination_reason="completed" if hits else "no_results",
        )
        return hits, {}, info
