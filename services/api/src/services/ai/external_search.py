import html
import json
import logging
import os
import re
import socket
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...schemas.ai import Hit

logger = logging.getLogger(__name__)

DEFAULT_TIER_1_DOMAINS = {
    "champagne.fr",
    "bourgogne-wines.com",
    "bivb.com",
    "decanter.com",
    "insideburgundy.com",
    "jaspermorrisinsideburgundy.com",
    "larvf.com",
    "vinous.com",
    "jancisrobinson.com",
    "wine-searcher.com",
    "wineadvocate.com",
    "burghound.com",
    "robertparker.com",
}
DEFAULT_TIER_2_DOMAINS = {
    "skurnik.com",
    "beckywasserman.com",
    "polanerselections.com",
    "thefinestbubble.com",
    "kermitlynch.com",
    "vinetrail.co.uk",
    "firadis.co.jp",
}
DEFAULT_INTERNAL_OFFICIAL_DOMAINS = {
    "ys.local",
}
DEFAULT_INTERNAL_PRIMARY_DOMAINS = {
    "cerp.winton.com.tw",
}
DEFAULT_DENY_DOMAINS = {
    "instagram.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "t.co",
    "threads.net",
    "reddit.com",
    "pinterest.com",
    "youtube.com",
    "tiktok.com",
    "vivino.com",
}
COMMERCE_KEYWORDS = {
    "buy",
    "cart",
    "checkout",
    "shop",
    "price",
    "product",
    "products",
    "sku",
    "retail",
    "store",
    "sale",
}
QUERY_STOP_WORDS = {
    "the",
    "and",
    "with",
    "for",
    "about",
    "what",
    "tell",
    "from",
    "this",
    "that",
    "wine",
    "wines",
    "ys",
    "estate",
    "winery",
}
BRAND_PROFILE_BOOSTERS = ["winery", "vineyard", "history", "winemaking"]
TERROIR_BOOSTERS = ["terroir", "soil", "vineyard"]
URL_BOOSTERS = ["official", "producer"]
SOURCE_VALIDATION_BOOSTERS = ["official", "source", "reference", "website"]
LATEST_INFO_BOOSTERS = ["latest", "recent", "news", "release"]
CRITIC_SCORE_BOOSTERS = ["critic", "score", "rating"]
AUTHORITATIVE_PROMPT_CATEGORIES = {
    "brand_profile",
    "terroir_comparison",
    "url_product_lookup",
    "source_validation",
    "critic_score_lookup",
}
AUTHORITATIVE_SEARCH_REASONS = {
    "authoritative_required",
    "source_validation",
    "latest_info",
    "manual_override",
    "low_internal_coverage",
}
AUTHORITATIVE_SOURCE_TIERS = {"internal_primary", "internal_official", "internal_approved", "Tier 1", "Tier 2"}


class ExternalSearchService:
    def __init__(self) -> None:
        self._enabled = os.getenv("EXTERNAL_SEARCH_ENABLED", "false").lower() in {"1", "true", "yes"}
        self._provider = os.getenv("EXTERNAL_SEARCH_PROVIDER", "google_cse").strip().lower() or "google_cse"
        self._fallback_provider = (
            os.getenv("EXTERNAL_SEARCH_FALLBACK_PROVIDER", "").strip().lower()
            or ("openai_web_search" if self._provider == "google_cse" else "google_cse")
        )
        self._openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self._openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        self._openai_web_search_model = (
            os.getenv("OPENAI_WEB_SEARCH_MODEL", "").strip()
            or os.getenv("OPENAI_FALLBACK_CHAT_MODEL", "").strip()
            or os.getenv("OPENAI_CHAT_MODEL", "").strip()
            or "gpt-5.4-mini"
        )
        self._openai_web_search_fallback_model = (
            os.getenv("OPENAI_WEB_SEARCH_FALLBACK_MODEL", "").strip()
            or os.getenv("OPENAI_FALLBACK_CHAT_MODEL", "").strip()
            or "gpt-5.4-mini"
        )
        self._openai_web_search_tool_type = os.getenv("OPENAI_WEB_SEARCH_TOOL_TYPE", "web_search").strip() or "web_search"
        self._google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        self._google_cse_id = os.getenv("GOOGLE_CSE_ID", "").strip()
        self._brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
        self._tier_1_domains = self._load_domains("EXTERNAL_SEARCH_TIER1_DOMAINS", DEFAULT_TIER_1_DOMAINS)
        self._tier_2_domains = self._load_domains("EXTERNAL_SEARCH_TIER2_DOMAINS", DEFAULT_TIER_2_DOMAINS)
        self._internal_official_domains = self._load_domains("INTERNAL_OFFICIAL_DOMAINS", DEFAULT_INTERNAL_OFFICIAL_DOMAINS)
        self._internal_primary_domains = self._load_domains("INTERNAL_PRIMARY_DOMAINS", DEFAULT_INTERNAL_PRIMARY_DOMAINS)
        self._deny_domains = self._load_domains("EXTERNAL_SEARCH_DENY_DOMAINS", DEFAULT_DENY_DOMAINS)
        self._result_limit = self._get_int_env("EXTERNAL_SEARCH_RESULT_LIMIT", 5, minimum=1, maximum=10)
        self._fetch_limit = self._get_int_env("EXTERNAL_SEARCH_FETCH_LIMIT", 3, minimum=1, maximum=5)
        self._authoritative_fetch_limit = self._get_int_env("EXTERNAL_SEARCH_AUTHORITATIVE_FETCH_LIMIT", 0, minimum=0, maximum=2)
        self._provider_limit = self._get_int_env("EXTERNAL_SEARCH_PROVIDER_LIMIT", 1, minimum=1, maximum=3)
        self._query_limit = self._get_int_env("EXTERNAL_SEARCH_QUERY_LIMIT", 2, minimum=1, maximum=5)
        self._budget_seconds = self._get_float_env("EXTERNAL_SEARCH_BUDGET_SECONDS", 35.0, minimum=5.0, maximum=120.0)
        self._google_timeout_seconds = self._get_float_env("EXTERNAL_SEARCH_GOOGLE_TIMEOUT_SECONDS", 10.0, minimum=1.0, maximum=60.0)
        self._brave_timeout_seconds = self._get_float_env("EXTERNAL_SEARCH_BRAVE_TIMEOUT_SECONDS", 10.0, minimum=1.0, maximum=60.0)
        self._openai_timeout_seconds = self._get_float_env("EXTERNAL_SEARCH_OPENAI_TIMEOUT_SECONDS", 18.0, minimum=1.0, maximum=60.0)
        self._fetch_timeout_seconds = self._get_float_env("EXTERNAL_SEARCH_FETCH_TIMEOUT_SECONDS", 8.0, minimum=1.0, maximum=30.0)

    def search(
        self,
        query: str,
        *,
        entity_hints: Optional[Dict[str, Any]] = None,
        prompt_category: Optional[str] = None,
        external_search_reason: Optional[str] = None,
        source_policy: str = "internal_preferred",
        needs_authoritative_sources: bool = False,
        internal_hit_count: int = 0,
        limit: int = 5,
        verified_domains: Optional[List[str]] = None,
        candidate_domains: Optional[List[str]] = None,
        request_deadline_at: Optional[float] = None,
    ) -> Tuple[List[Hit], Dict[str, str], Dict[str, Any]]:
        started = time.monotonic()
        errors: Dict[str, str] = {}
        info: Dict[str, Any] = {
            "attempted": False,
            "reason": external_search_reason,
            "provider": None,
            "query": None,
            "queries": [],
            "hit_count_pre_filter": 0,
            "hit_count_post_filter": 0,
            "fetched_url_count": 0,
            "authoritative_hit_count": 0,
            "quality_gate": "not_attempted",
            "provider_attempts": [],
            "seeded_domains": {
                "verified": list(verified_domains or []),
                "candidate": list(candidate_domains or []),
            },
            "verified_domain_used": None,
            "candidate_domain_used": None,
            "sources": [],
            "termination_reason": None,
            "budget_exhausted": False,
            "provider_unavailable": False,
            "duration_ms": 0.0,
        }
        if not self.should_search(
            source_policy=source_policy,
            needs_authoritative_sources=needs_authoritative_sources,
            internal_hit_count=internal_hit_count,
            external_search_reason=external_search_reason,
        ):
            return [], errors, info

        info["attempted"] = True
        authoritative_search = self._requires_authoritative_quality(
            prompt_category=prompt_category,
            external_search_reason=external_search_reason,
            needs_authoritative_sources=needs_authoritative_sources,
            source_policy=source_policy,
        )
        budget_deadline = started + self._budget_seconds
        effective_deadline = min(
            budget_deadline,
            request_deadline_at if request_deadline_at is not None else budget_deadline,
        )
        if self._remaining_seconds(effective_deadline) <= 0:
            info["termination_reason"] = self._deadline_termination_reason(
                budget_deadline=budget_deadline,
                request_deadline_at=request_deadline_at,
            )
            info["budget_exhausted"] = info["termination_reason"] in {"budget_exhausted", "request_deadline_exceeded"}
            info["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
            return [], errors, info
        providers = self._provider_order(
            prompt_category=prompt_category,
            external_search_reason=external_search_reason,
            verified_domains=verified_domains or [],
            authoritative_search=authoritative_search,
        )
        providers = providers[: max(1, self._provider_limit)]

        best_attempt: Optional[Dict[str, Any]] = None
        best_hits: List[Hit] = []
        for provider in providers:
            if self._remaining_seconds(effective_deadline) <= 0:
                info["termination_reason"] = self._deadline_termination_reason(
                    budget_deadline=budget_deadline,
                    request_deadline_at=request_deadline_at,
                )
                info["budget_exhausted"] = True
                break
            attempt_hits, attempt_errors, attempt_info = self._search_with_provider(
                provider,
                query,
                entity_hints=entity_hints or {},
                prompt_category=prompt_category,
                external_search_reason=external_search_reason,
                authoritative_search=authoritative_search,
                limit=limit,
                verified_domains=verified_domains or [],
                candidate_domains=candidate_domains or [],
                effective_deadline=effective_deadline,
                budget_deadline=budget_deadline,
                request_deadline_at=request_deadline_at,
            )
            if attempt_errors:
                errors.update(attempt_errors)
            info["provider_attempts"].append(attempt_info)
            if best_attempt is None or self._attempt_better_than(attempt_info, best_attempt):
                best_attempt = attempt_info
                best_hits = attempt_hits
            if attempt_info.get("quality_gate") == "provider_unavailable":
                info["provider_unavailable"] = True
            if attempt_info.get("termination_reason"):
                info["termination_reason"] = attempt_info.get("termination_reason")
            if attempt_info.get("budget_exhausted"):
                info["budget_exhausted"] = True
            if self._attempt_satisfies_quality(attempt_info, authoritative_search=authoritative_search):
                break

        if best_attempt:
            info.update(
                {
                    "provider": best_attempt.get("provider"),
                    "query": best_attempt.get("query"),
                    "queries": best_attempt.get("queries") or [],
                    "hit_count_pre_filter": best_attempt.get("hit_count_pre_filter", 0),
                    "hit_count_post_filter": best_attempt.get("hit_count_post_filter", 0),
                    "fetched_url_count": best_attempt.get("fetched_url_count", 0),
                    "authoritative_hit_count": best_attempt.get("authoritative_hit_count", 0),
                    "quality_gate": best_attempt.get("quality_gate", "not_attempted"),
                    "verified_domain_used": best_attempt.get("verified_domain_used"),
                    "candidate_domain_used": best_attempt.get("candidate_domain_used"),
                    "sources": best_attempt.get("sources") or [],
                    "termination_reason": info.get("termination_reason") or best_attempt.get("termination_reason"),
                    "budget_exhausted": bool(info.get("budget_exhausted") or best_attempt.get("budget_exhausted")),
                    "provider_unavailable": bool(info.get("provider_unavailable") or best_attempt.get("provider_unavailable")),
                    "model": best_attempt.get("model"),
                }
            )
        info["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
        return best_hits, errors, info

    def should_search(
        self,
        *,
        source_policy: str,
        needs_authoritative_sources: bool,
        internal_hit_count: int,
        external_search_reason: Optional[str] = None,
    ) -> bool:
        if not self._enabled:
            return False
        if (source_policy or "").strip() == "internal_only":
            return False
        if external_search_reason:
            return True
        if needs_authoritative_sources:
            return True
        return (source_policy or "").strip() == "authoritative_external_required" and internal_hit_count < 3

    def _provider_order(
        self,
        *,
        prompt_category: Optional[str],
        external_search_reason: Optional[str],
        verified_domains: List[str],
        authoritative_search: bool,
    ) -> List[str]:
        primary = self._provider
        if (external_search_reason or "").strip() == "latest_info":
            if self._openai_api_key:
                primary = "openai_web_search"
            elif self._brave_api_key:
                primary = "brave_search"
            else:
                primary = self._provider
        elif verified_domains:
            primary = "google_cse" if self._google_api_key and self._google_cse_id else self._provider

        providers: List[str] = []
        for provider in [primary, self._fallback_provider]:
            normalized = (provider or "").strip().lower()
            if normalized and normalized not in providers:
                providers.append(normalized)
        if authoritative_search:
            return providers[:1]
        if primary == "openai_web_search":
            for provider in ("google_cse", "brave_search"):
                if provider == "google_cse" and (not self._google_api_key or not self._google_cse_id):
                    continue
                if provider == "brave_search" and not self._brave_api_key:
                    continue
                if provider not in providers:
                    providers.append(provider)
        elif primary == "google_cse" and self._openai_api_key and "openai_web_search" not in providers:
            providers.append("openai_web_search")
        return providers

    def _search_with_provider(
        self,
        provider: str,
        query: str,
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
        external_search_reason: Optional[str],
        authoritative_search: bool,
        limit: int,
        verified_domains: List[str],
        candidate_domains: List[str],
        effective_deadline: float,
        budget_deadline: float,
        request_deadline_at: Optional[float],
    ) -> Tuple[List[Hit], Dict[str, str], Dict[str, Any]]:
        errors: Dict[str, str] = {}
        attempt: Dict[str, Any] = {
            "provider": provider,
            "query": None,
            "queries": [],
            "hit_count_pre_filter": 0,
            "hit_count_post_filter": 0,
            "fetched_url_count": 0,
            "authoritative_hit_count": 0,
            "quality_gate": "not_attempted",
            "verified_domain_used": verified_domains[0] if verified_domains else None,
            "candidate_domain_used": None,
            "sources": [],
            "termination_reason": None,
            "budget_exhausted": False,
            "provider_unavailable": False,
            "model": self._openai_web_search_model if provider == "openai_web_search" else None,
        }
        if provider == "google_cse" and (not self._google_api_key or not self._google_cse_id):
            errors["external_search"] = "Google CSE is not configured."
            attempt["quality_gate"] = "provider_unavailable"
            attempt["provider_unavailable"] = True
            return [], errors, attempt
        if provider == "brave_search" and not self._brave_api_key:
            errors["external_search"] = "Brave Search API is not configured."
            attempt["quality_gate"] = "provider_unavailable"
            attempt["provider_unavailable"] = True
            return [], errors, attempt
        if provider == "openai_web_search" and not self._openai_api_key:
            errors["external_search"] = "OpenAI web search is not configured."
            attempt["quality_gate"] = "provider_unavailable"
            attempt["provider_unavailable"] = True
            return [], errors, attempt
        if provider not in {"google_cse", "brave_search", "openai_web_search"}:
            errors["external_search"] = f"Unsupported provider: {provider}"
            attempt["quality_gate"] = "provider_unavailable"
            attempt["provider_unavailable"] = True
            return [], errors, attempt

        search_queries = self.build_search_queries(
            query,
            entity_hints,
            prompt_category=prompt_category,
            external_search_reason=external_search_reason,
            verified_domains=verified_domains,
            candidate_domains=candidate_domains,
        )
        search_queries = search_queries[: max(1, self._query_limit)]
        attempt["query"] = search_queries[0] if search_queries else None
        attempt["queries"] = list(search_queries)

        candidates: List[Dict[str, Any]] = []
        search_limit = min(limit or self._result_limit, self._result_limit)
        verified_domain_used = None
        candidate_domain_used = None
        sources: List[Dict[str, Any]] = []
        preferred_domains = list(verified_domains or [])
        fallback_domains = list(candidate_domains or [])
        for search_query in search_queries:
            if self._remaining_seconds(effective_deadline) <= 0:
                attempt["termination_reason"] = self._deadline_termination_reason(
                    budget_deadline=budget_deadline,
                    request_deadline_at=request_deadline_at,
                )
                attempt["budget_exhausted"] = True
                attempt["quality_gate"] = "budget_exhausted"
                errors["external_search"] = "External search budget exhausted before provider query completed."
                return [], errors, attempt
            if search_query.startswith("site:"):
                seeded_domain = search_query.split()[0].replace("site:", "").strip().lower()
                if seeded_domain in {domain.lower() for domain in verified_domains}:
                    verified_domain_used = seeded_domain
                elif seeded_domain in {domain.lower() for domain in candidate_domains}:
                    candidate_domain_used = seeded_domain
            try:
                payload = self._provider_search(
                    provider,
                    search_query,
                    limit=search_limit,
                    allowed_domains=preferred_domains or fallback_domains,
                    timeout_s=self._provider_timeout_seconds(provider, effective_deadline),
                )
            except Exception as exc:
                logger.warning("External search failed: %s", exc)
                errors["external_search"] = f"{type(exc).__name__}: {exc}"
                attempt["termination_reason"] = self._classify_exception_termination_reason(exc)
                attempt["budget_exhausted"] = attempt["termination_reason"] in {"budget_exhausted", "request_deadline_exceeded"}
                attempt["quality_gate"] = "provider_timeout" if attempt["termination_reason"] == "provider_timeout" else "provider_error"
                return [], errors, attempt
            sources = self._merge_candidates(sources, self._extract_payload_sources(payload, provider))
            candidates = self._merge_candidates(candidates, self._results_to_candidates(payload, provider))
            filtered_candidates = self._filter_candidates(
                candidates,
                query=query,
                entity_hints=entity_hints,
                prompt_category=prompt_category,
            )
            if self._query_cascade_satisfied(
                filtered_candidates,
                authoritative_search=authoritative_search,
                requested_limit=max(1, limit or self._result_limit),
            ):
                break

        attempt["hit_count_pre_filter"] = len(candidates)
        filtered_candidates = self._filter_candidates(
            candidates,
            query=query,
            entity_hints=entity_hints,
            prompt_category=prompt_category,
        )
        attempt["hit_count_post_filter"] = len(filtered_candidates)
        attempt["authoritative_hit_count"] = self._count_authoritative_candidates(filtered_candidates)
        attempt["quality_gate"] = self._quality_gate_label(
            filtered_candidates,
            authoritative_search=authoritative_search,
        )
        hits, fetched_url_count = self._candidates_to_hits(
            filtered_candidates,
            entity_hints=entity_hints,
            prompt_category=prompt_category,
            fetch_limit=min(
                self._authoritative_fetch_limit if authoritative_search else self._fetch_limit,
                max(1, limit or self._result_limit),
            ),
            limit=max(1, limit or self._result_limit),
            timeout_s=self._fetch_timeout_seconds,
        )
        accepted_authoritative_hits = self._count_authoritative_hits_from_hits(hits)
        attempt["hit_count_post_filter"] = len(hits)
        attempt["fetched_url_count"] = fetched_url_count
        attempt["authoritative_hit_count"] = accepted_authoritative_hits
        attempt["quality_gate"] = self._quality_gate_label_from_hits(
            hits,
            authoritative_search=authoritative_search,
        )
        attempt["verified_domain_used"] = verified_domain_used
        attempt["candidate_domain_used"] = candidate_domain_used
        attempt["sources"] = sources[: max(1, limit or self._result_limit)]
        return hits, errors, attempt

    def _provider_search(
        self,
        provider: str,
        query: str,
        *,
        limit: int,
        allowed_domains: Optional[List[str]] = None,
        timeout_s: float,
    ) -> Dict[str, Any]:
        if provider == "google_cse":
            return self._google_search(query, limit=limit, timeout_s=timeout_s)
        if provider == "brave_search":
            return self._brave_search(query, limit=limit, timeout_s=timeout_s)
        return self._openai_web_search(query, limit=limit, allowed_domains=allowed_domains or [], timeout_s=timeout_s)

    @staticmethod
    def _attempt_satisfies_quality(attempt: Dict[str, Any], *, authoritative_search: bool) -> bool:
        if not authoritative_search:
            return int(attempt.get("hit_count_post_filter") or 0) > 0
        return str(attempt.get("quality_gate") or "") in {"authoritative_hits_available"}

    @staticmethod
    def _attempt_better_than(current: Dict[str, Any], previous: Dict[str, Any]) -> bool:
        current_score = (
            int(current.get("authoritative_hit_count") or 0),
            int(current.get("hit_count_post_filter") or 0),
            int(current.get("fetched_url_count") or 0),
        )
        previous_score = (
            int(previous.get("authoritative_hit_count") or 0),
            int(previous.get("hit_count_post_filter") or 0),
            int(previous.get("fetched_url_count") or 0),
        )
        return current_score > previous_score

    @staticmethod
    def build_search_query(
        query: str,
        entity_hints: Dict[str, Any],
        *,
        prompt_category: Optional[str] = None,
        external_search_reason: Optional[str] = None,
    ) -> str:
        producer_value = entity_hints.get("producer")
        parts: List[str] = []
        producer_first_categories = {
            "brand_profile",
            "terroir_comparison",
            "url_product_lookup",
            "source_validation",
            "critic_score_lookup",
        }
        if (
            (prompt_category in producer_first_categories or external_search_reason == "latest_info")
            and isinstance(producer_value, str)
            and producer_value.strip()
        ):
            parts.extend(ExternalSearchService._producer_query_terms(producer_value))
        else:
            parts.append((query or "").strip())
        if isinstance(producer_value, str) and producer_value.strip():
            parts.extend(ExternalSearchService._producer_query_terms(producer_value))
        for key in ("producer", "region", "style", "classification", "grape", "grape_varieties"):
            value = entity_hints.get(key)
            if isinstance(value, list):
                parts.extend(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                parts.append(value.strip())

        boosters: List[str] = []
        if prompt_category == "brand_profile":
            boosters = BRAND_PROFILE_BOOSTERS
        elif prompt_category == "terroir_comparison":
            boosters = TERROIR_BOOSTERS
        elif prompt_category == "url_product_lookup":
            boosters = URL_BOOSTERS
        elif prompt_category == "source_validation":
            boosters = SOURCE_VALIDATION_BOOSTERS
        elif prompt_category == "critic_score_lookup":
            boosters = CRITIC_SCORE_BOOSTERS
        elif external_search_reason == "latest_info":
            boosters = LATEST_INFO_BOOSTERS

        parts.extend(boosters)
        deduped: List[str] = []
        for part in parts:
            if part and part not in deduped:
                deduped.append(part)
        return " ".join(deduped).strip()

    @staticmethod
    def build_search_queries(
        query: str,
        entity_hints: Dict[str, Any],
        *,
        prompt_category: Optional[str] = None,
        external_search_reason: Optional[str] = None,
        verified_domains: Optional[List[str]] = None,
        candidate_domains: Optional[List[str]] = None,
    ) -> List[str]:
        primary = ExternalSearchService.build_search_query(
            query,
            entity_hints,
            prompt_category=prompt_category,
            external_search_reason=external_search_reason,
        )
        producer_value = entity_hints.get("producer")
        producer_terms: List[str] = []
        if isinstance(producer_value, list):
            for item in producer_value:
                producer_terms.extend(ExternalSearchService._producer_query_terms(str(item)))
        elif isinstance(producer_value, str):
            producer_terms = ExternalSearchService._producer_query_terms(producer_value)
        producer = producer_terms[0] if producer_terms else ""
        stripped_producer = producer_terms[-1] if producer_terms else ""
        region = ExternalSearchService._string_hint(entity_hints.get("region"))
        style = ExternalSearchService._string_hint(entity_hints.get("style"))

        fallback_queries: List[str] = []
        primary_base = " ".join(primary.split()).strip()
        for domain in (verified_domains or [])[:3]:
            if domain and primary_base:
                fallback_queries.append(f"site:{domain} {primary_base}".strip())
        if primary_base:
            fallback_queries.append(primary_base)
        if prompt_category == "brand_profile":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "official", "winery", "vineyard", "history"] if part))
            fallback_queries.append(" ".join(part for part in [producer or stripped_producer, region, style, "producer", "official"] if part))
        elif prompt_category == "source_validation":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "official", "source", "reference"] if part))
            fallback_queries.append(" ".join(part for part in [producer or stripped_producer, "official", "website"] if part))
        elif external_search_reason == "latest_info":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "latest", "news", "release"] if part))
        elif prompt_category == "url_product_lookup":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "official", "site", "url"] if part))
        elif prompt_category == "terroir_comparison":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "terroir", "soil", "vineyard"] if part))
        elif prompt_category == "critic_score_lookup":
            fallback_queries.append(" ".join(part for part in [stripped_producer or producer, region, "critic", "score"] if part))

        if stripped_producer and stripped_producer.lower() != producer.lower():
            fallback_queries.append(" ".join(part for part in [stripped_producer, region, "official"] if part))
        candidate_base = " ".join(part for part in [stripped_producer or producer, region, "official"] if part) or primary_base
        for domain in (candidate_domains or [])[:2]:
            if domain and candidate_base:
                fallback_queries.append(f"site:{domain} {candidate_base}".strip())

        deduped: List[str] = []
        for item in fallback_queries:
            normalized = " ".join((item or "").split()).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _google_search(self, query: str, *, limit: int, timeout_s: float) -> Dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "key": self._google_api_key,
                "cx": self._google_cse_id,
                "q": query,
                "num": max(1, min(limit, 10)),
            }
        )
        url = f"https://www.googleapis.com/customsearch/v1?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "YS AI/1.0"})
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
        return json.loads(body.decode("utf-8"))

    def _brave_search(self, query: str, *, limit: int, timeout_s: float) -> Dict[str, Any]:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "count": max(1, min(limit, 20)),
                "text_decorations": 0,
            }
        )
        url = f"https://api.search.brave.com/res/v1/web/search?{params}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "YS AI/1.0",
                "Accept": "application/json",
                "X-Subscription-Token": self._brave_api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
        return json.loads(body.decode("utf-8"))

    def _openai_web_search(self, query: str, *, limit: int, allowed_domains: List[str], timeout_s: float) -> Dict[str, Any]:
        attempted_models: List[str] = []
        for model_name in self._candidate_openai_web_search_models():
            attempted_models.append(model_name)
            try:
                return self._run_openai_web_search_request(
                    query,
                    allowed_domains=allowed_domains,
                    model_name=model_name,
                    timeout_s=timeout_s,
                )
            except RuntimeError as exc:
                if not self._is_retryable_openai_model_error(str(exc)):
                    raise
                logger.warning("OpenAI web search model %s unavailable, retrying fallback if configured.", model_name)
                continue
        raise RuntimeError(
            "OpenAI web search failed for all configured models: "
            + ", ".join(model for model in attempted_models if model)
        )

    def _candidate_openai_web_search_models(self) -> List[str]:
        models: List[str] = []
        for model_name in [self._openai_web_search_model, self._openai_web_search_fallback_model]:
            normalized = (model_name or "").strip()
            if normalized and normalized not in models:
                models.append(normalized)
        return models or ["gpt-5.4-mini"]

    def _run_openai_web_search_request(
        self,
        query: str,
        *,
        allowed_domains: List[str],
        model_name: str,
        timeout_s: float,
    ) -> Dict[str, Any]:
        payload = self._build_openai_web_search_payload(
            query,
            allowed_domains=allowed_domains,
            model_name=model_name,
        )
        try:
            return self._send_openai_responses_request(payload, timeout_s=timeout_s)
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="ignore")
            if self._openai_web_search_tool_type != "web_search_preview" and exc.code in {400, 422}:
                retry_payload = self._build_openai_web_search_payload(
                    query,
                    allowed_domains=allowed_domains,
                    tool_type="web_search_preview",
                    model_name=model_name,
                )
                return self._send_openai_responses_request(retry_payload, timeout_s=timeout_s)
            raise RuntimeError(f"OpenAI web search failed: HTTP {exc.code} {error_body}") from exc

    def _send_openai_responses_request(self, payload: Dict[str, Any], *, timeout_s: float) -> Dict[str, Any]:
        request = urllib.request.Request(
            f"{self._openai_base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._openai_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read()
        return json.loads(body.decode("utf-8"))

    @staticmethod
    def _is_retryable_openai_model_error(message: str) -> bool:
        lowered = str(message or "").lower()
        return "model_not_found" in lowered or "does not have access to model" in lowered

    def _build_openai_web_search_payload(
        self,
        query: str,
        *,
        allowed_domains: List[str],
        tool_type: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        tool_name = (tool_type or self._openai_web_search_tool_type or "web_search").strip()
        constrained_query = query
        if allowed_domains:
            seeded = " OR ".join(f"site:{domain}" for domain in allowed_domains[:5])
            constrained_query = f"{query}\nPrioritize these domains when relevant: {seeded}"
        return {
            "model": (model_name or self._openai_web_search_model).strip(),
            "input": constrained_query,
            "tools": [{"type": tool_name}],
        }

    def _results_to_candidates(self, payload: Dict[str, Any], provider: str) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        if provider == "brave_search":
            items = ((payload.get("web") or {}).get("results") or []) if isinstance(payload, dict) else []
        elif provider == "openai_web_search":
            items = self._extract_payload_sources(payload, provider)
        else:
            items = payload.get("items") or []
        for item in items:
            link = str(item.get("link") or item.get("url") or "").strip()
            domain = urllib.parse.urlparse(link).netloc.lower().strip()
            if not link or not domain:
                continue
            if provider == "brave_search":
                published_hint = item.get("page_age") or item.get("age")
                extra_snippets = item.get("extra_snippets") or []
                if not isinstance(extra_snippets, list):
                    extra_snippets = []
                snippet = " ".join(
                    part
                    for part in [
                        str(item.get("description") or "").strip(),
                        " ".join(str(part or "").strip() for part in extra_snippets if str(part or "").strip()),
                    ]
                    if part
                ).strip()
                title = str(item.get("title") or "").strip()
            elif provider == "openai_web_search":
                published_hint = item.get("published_hint")
                snippet = str(item.get("snippet") or item.get("text") or "").strip()
                title = str(item.get("title") or "").strip()
            else:
                pagemap = item.get("pagemap") if isinstance(item.get("pagemap"), dict) else {}
                metatags = (pagemap.get("metatags") or [{}])[0] if isinstance(pagemap.get("metatags"), list) else {}
                published_hint = metatags.get("article:published_time") or metatags.get("og:updated_time")
                snippet = str(item.get("snippet") or "").strip()
                title = str(item.get("title") or "").strip()
            candidates.append(
                {
                    "title": title,
                    "link": link,
                    "domain": domain,
                    "snippet": snippet,
                    "published_hint": published_hint,
                    "source_tier": self._classify_domain(domain),
                    "source_provider": provider,
                }
            )
        return candidates

    def _extract_payload_sources(self, payload: Dict[str, Any], provider: str) -> List[Dict[str, Any]]:
        if provider != "openai_web_search" or not isinstance(payload, dict):
            return []
        candidates: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in self._walk_openai_sources(payload):
            link = str(item.get("url") or item.get("link") or "").strip()
            domain = urllib.parse.urlparse(link).netloc.lower().strip()
            if not link or not domain or link in seen:
                continue
            seen.add(link)
            candidates.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "link": link,
                    "url": link,
                    "domain": domain,
                    "snippet": str(item.get("snippet") or item.get("text") or "").strip(),
                    "published_hint": item.get("published_hint"),
                    "source_tier": self._classify_domain(domain),
                    "source_provider": provider,
                }
            )
        return candidates

    def _walk_openai_sources(self, payload: Any) -> List[Dict[str, Any]]:
        discovered: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            if payload.get("type") == "url_citation" and payload.get("url"):
                discovered.append(
                    {
                        "title": payload.get("title"),
                        "url": payload.get("url"),
                        "snippet": payload.get("text") or payload.get("title") or "",
                    }
                )
            elif payload.get("url") and any(key in payload for key in ("title", "snippet", "text")):
                discovered.append(
                    {
                        "title": payload.get("title"),
                        "url": payload.get("url"),
                        "snippet": payload.get("snippet") or payload.get("text") or "",
                        "published_hint": payload.get("published_hint"),
                    }
                )
            for value in payload.values():
                discovered.extend(self._walk_openai_sources(value))
        elif isinstance(payload, list):
            for item in payload:
                discovered.extend(self._walk_openai_sources(item))
        return discovered

    def _filter_candidates(
        self,
        candidates: List[Dict[str, Any]],
        *,
        query: str,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for candidate in candidates:
            if self._is_denied_domain(candidate["domain"]):
                continue
            if self._looks_like_forum_or_social(candidate):
                continue
            if self._looks_like_commerce_page(candidate) and candidate.get("source_tier") == "Tier 3":
                continue
            filtered.append(candidate)

        filtered.sort(
            key=lambda candidate: self._sort_key(
                candidate,
                query=query,
                entity_hints=entity_hints,
                prompt_category=prompt_category,
            )
        )
        return filtered

    def _candidates_to_hits(
        self,
        candidates: List[Dict[str, Any]],
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
        fetch_limit: int,
        limit: int,
        timeout_s: float,
    ) -> Tuple[List[Hit], int]:
        hits: List[Hit] = []
        fetched_url_count = 0
        for index, candidate in enumerate(candidates[:limit]):
            fetched_excerpt = None
            fetch_status = "not_attempted"
            if index < fetch_limit:
                fetch_status = "pending"
                fetched_excerpt = self._fetch_candidate_excerpt(
                    candidate["link"],
                    entity_hints=entity_hints,
                    prompt_category=prompt_category,
                    timeout_s=timeout_s,
                )
                if fetched_excerpt:
                    fetched_url_count += 1
                    fetch_status = "fetched"
                else:
                    fetch_status = "failed"

            title = candidate.get("title") or ""
            snippet = candidate.get("snippet") or ""
            text = fetched_excerpt or snippet or title
            summary = title or snippet or text[:180]
            if not self._candidate_matches_entity(
                candidate,
                text=text,
                summary=summary,
                entity_hints=entity_hints,
                prompt_category=prompt_category,
            ):
                continue
            hits.append(
                Hit(
                    id=candidate["link"],
                    text=text,
                    summary=summary,
                    meta={
                        "title": title,
                        "url": candidate["link"],
                        "domain": candidate["domain"],
                        "published_hint": candidate.get("published_hint"),
                        "snippet": snippet,
                        "source": "external_search",
                        "source_provider": candidate.get("source_provider") or self._provider,
                        "source_tier": candidate["source_tier"],
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "fetch_status": fetch_status,
                    },
                    source_type="external",
                    source_tier=candidate["source_tier"],
                )
            )
        return hits, fetched_url_count

    def _candidate_matches_entity(
        self,
        candidate: Dict[str, Any],
        *,
        text: str,
        summary: str,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> bool:
        producer = self._string_hint(entity_hints.get("producer")).lower()
        if not producer:
            return True
        haystack = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("snippet") or ""),
                str(candidate.get("link") or ""),
                str(summary or ""),
                str(text or ""),
            ]
        ).lower()
        producer_tokens = [token for token in re.split(r"[^a-z0-9]+", producer) if token]
        if producer in haystack:
            return True
        if producer_tokens and all(token in haystack for token in producer_tokens):
            return True
        if prompt_category == "latest_info" and len(producer_tokens) >= 2 and any(token in haystack for token in producer_tokens):
            return False
        return False

    @staticmethod
    def _merge_candidates(existing: List[Dict[str, Any]], new_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in existing + new_candidates:
            link = str(candidate.get("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            merged.append(candidate)
        return merged

    def _fetch_candidate_excerpt(
        self,
        url: str,
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
        timeout_s: float,
    ) -> Optional[str]:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "YS AI/1.0"})
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                    return None
                body = response.read(350000)
        except Exception as exc:
            logger.debug("Fetch external page failed for %s: %s", url, exc)
            return None

        try:
            html_text = body.decode("utf-8", errors="ignore")
        except Exception:
            return None
        extracted = self._extract_text_from_html(html_text)
        if not extracted:
            return None
        return self._build_excerpt(
            extracted,
            entity_hints=entity_hints,
            prompt_category=prompt_category,
        )

    @staticmethod
    def _extract_text_from_html(raw_html: str) -> str:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw_html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<!--.*?-->", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _build_excerpt(
        self,
        text: str,
        *,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> str:
        tokens: List[str] = []
        for key in ("producer", "region", "style", "classification"):
            value = entity_hints.get(key)
            if isinstance(value, list):
                tokens.extend(str(item).strip().lower() for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                tokens.append(value.strip().lower())
        if prompt_category == "brand_profile":
            tokens.extend(["vineyard", "history", "winemaking"])
        segments = re.split(r"(?<=[\.\!\?。；;])\s+", text)
        matched: List[str] = []
        for segment in segments:
            cleaned = " ".join(segment.split())
            lowered = cleaned.lower()
            if len(cleaned) < 40:
                continue
            if tokens and any(token in lowered for token in tokens):
                matched.append(cleaned)
            if len(matched) >= 4:
                break
        if matched:
            return " ".join(matched)[:1400].rstrip()
        return text[:1400].rstrip()

    def _classify_domain(self, domain: str) -> str:
        normalized = domain.lower().strip()
        for candidate in self._internal_official_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                return "internal_official"
        for candidate in self._internal_primary_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                return "internal_primary"
        for candidate in self._tier_1_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                return "Tier 1"
        for candidate in self._tier_2_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                return "Tier 2"
        return "Tier 3"

    def _is_denied_domain(self, domain: str) -> bool:
        normalized = domain.lower().strip()
        for candidate in self._deny_domains:
            if normalized == candidate or normalized.endswith(f".{candidate}"):
                return True
        return False

    @staticmethod
    def _looks_like_forum_or_social(candidate: Dict[str, Any]) -> bool:
        haystack = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("snippet") or ""),
                str(candidate.get("link") or ""),
            ]
        ).lower()
        return any(token in haystack for token in ["forum", "thread", "instagram", "facebook", "reddit"])

    @staticmethod
    def _looks_like_commerce_page(candidate: Dict[str, Any]) -> bool:
        haystack = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("snippet") or ""),
                str(candidate.get("link") or ""),
            ]
        ).lower()
        return any(token in haystack for token in COMMERCE_KEYWORDS)

    def _sort_key(
        self,
        candidate: Dict[str, Any],
        *,
        query: str,
        entity_hints: Dict[str, Any],
        prompt_category: Optional[str],
    ) -> Tuple[int, int, int, int, int, str]:
        tier_rank = {
            "internal_primary": 0,
            "internal_official": 0,
            "Tier 1": 1,
            "Tier 2": 2,
            "Tier 3": 3,
        }.get(candidate.get("source_tier") or "Tier 3", 4)
        entity_score = self._entity_match_score(candidate, entity_hints)
        region_score = self._region_match_score(candidate, entity_hints, prompt_category=prompt_category)
        freshness_score = self._freshness_score(candidate.get("published_hint"))
        lexical_score = self._lexical_score(query, candidate)
        return (
            tier_rank,
            -entity_score,
            -region_score,
            -freshness_score,
            -lexical_score,
            str(candidate.get("domain") or ""),
        )

    @staticmethod
    def _entity_match_score(candidate: Dict[str, Any], entity_hints: Dict[str, Any]) -> int:
        producer = entity_hints.get("producer")
        return ExternalSearchService._match_score(candidate, producer)

    @staticmethod
    def _region_match_score(
        candidate: Dict[str, Any],
        entity_hints: Dict[str, Any],
        *,
        prompt_category: Optional[str],
    ) -> int:
        score = 0
        for key in ("region", "style", "classification", "grape", "grape_varieties"):
            score += ExternalSearchService._match_score(candidate, entity_hints.get(key))
        if prompt_category == "brand_profile":
            haystack = " ".join(
                [
                    str(candidate.get("title") or ""),
                    str(candidate.get("snippet") or ""),
                ]
            ).lower()
            score += int("vineyard" in haystack or "history" in haystack or "winemaking" in haystack)
        return score

    @staticmethod
    def _match_score(candidate: Dict[str, Any], value: Any) -> int:
        if not value:
            return 0
        values = value if isinstance(value, list) else [value]
        haystack = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("snippet") or ""),
                str(candidate.get("link") or ""),
            ]
        ).lower()
        score = 0
        for item in values:
            token = str(item or "").strip().lower()
            if not token:
                continue
            if token == "burgundy":
                if "burgundy" in haystack or "bourgogne" in haystack:
                    score += 1
                continue
            if token in haystack:
                score += 1
        return score

    @staticmethod
    def _freshness_score(published_hint: Any) -> int:
        if not published_hint:
            return 0
        snippet = str(published_hint).strip()
        if snippet.endswith("Z"):
            snippet = snippet[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(snippet)
        except ValueError:
            return 0
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc)
        return int(parsed.timestamp())

    @staticmethod
    def _lexical_score(query: str, candidate: Dict[str, Any]) -> int:
        terms = [
            token
            for token in re.split(r"[^a-z0-9]+", (query or "").lower())
            if len(token) > 2 and token not in QUERY_STOP_WORDS
        ]
        if not terms:
            return 0
        haystack = " ".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("snippet") or ""),
                str(candidate.get("link") or ""),
            ]
        ).lower()
        return sum(1 for token in terms if token in haystack)

    @staticmethod
    def _string_hint(value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                normalized = ExternalSearchService._string_hint(item)
                if normalized:
                    return normalized
            return ""
        if isinstance(value, str):
            return value.strip()
        return ""

    @staticmethod
    def _count_authoritative_candidates(candidates: List[Dict[str, Any]]) -> int:
        return sum(
            1
            for candidate in candidates
            if str(candidate.get("source_tier") or "").strip() in AUTHORITATIVE_SOURCE_TIERS
        )

    @staticmethod
    def _count_authoritative_hits_from_hits(hits: List[Hit]) -> int:
        return sum(
            1
            for hit in hits
            if str(hit.source_tier or (hit.meta or {}).get("source_tier") or "").strip() in AUTHORITATIVE_SOURCE_TIERS
        )

    @staticmethod
    def _requires_authoritative_quality(
        *,
        prompt_category: Optional[str],
        external_search_reason: Optional[str],
        needs_authoritative_sources: bool,
        source_policy: str,
    ) -> bool:
        normalized_policy = (source_policy or "").strip()
        if normalized_policy == "internal_only":
            return False
        if needs_authoritative_sources:
            return True
        if prompt_category in AUTHORITATIVE_PROMPT_CATEGORIES:
            return True
        return (external_search_reason or "").strip() in AUTHORITATIVE_SEARCH_REASONS

    @classmethod
    def _query_cascade_satisfied(
        cls,
        candidates: List[Dict[str, Any]],
        *,
        authoritative_search: bool,
        requested_limit: int,
    ) -> bool:
        if authoritative_search:
            return cls._count_authoritative_candidates(candidates) > 0
        return len(candidates) >= requested_limit

    @classmethod
    def _quality_gate_label(
        cls,
        candidates: List[Dict[str, Any]],
        *,
        authoritative_search: bool,
    ) -> str:
        if not candidates:
            return "no_hits"
        authoritative_hits = cls._count_authoritative_candidates(candidates)
        if authoritative_search:
            if authoritative_hits > 0:
                return "authoritative_hits_available"
            return "tier3_only"
        return "best_effort"

    @classmethod
    def _quality_gate_label_from_hits(
        cls,
        hits: List[Hit],
        *,
        authoritative_search: bool,
    ) -> str:
        if not hits:
            return "no_hits"
        authoritative_hits = cls._count_authoritative_hits_from_hits(hits)
        if authoritative_search:
            if authoritative_hits > 0:
                return "authoritative_hits_available"
            return "tier3_only"
        return "best_effort"

    @staticmethod
    def _load_domains(env_name: str, defaults: set[str]) -> set[str]:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return set(defaults)
        return {
            item.strip().lower()
            for item in raw.split(",")
            if item.strip()
        }

    @staticmethod
    def _get_int_env(env_name: str, default: int, *, minimum: int, maximum: int) -> int:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _get_float_env(env_name: str, default: float, *, minimum: float, maximum: float) -> float:
        raw = os.getenv(env_name, "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _remaining_seconds(deadline_at: float) -> float:
        return max(0.0, deadline_at - time.monotonic())

    def _provider_timeout_seconds(self, provider: str, effective_deadline: float) -> float:
        configured = self._openai_timeout_seconds
        if provider == "google_cse":
            configured = self._google_timeout_seconds
        elif provider == "brave_search":
            configured = self._brave_timeout_seconds
        remaining = self._remaining_seconds(effective_deadline)
        return max(1.0, min(configured, remaining))

    @staticmethod
    def _deadline_termination_reason(
        *,
        budget_deadline: float,
        request_deadline_at: Optional[float],
    ) -> str:
        if request_deadline_at is not None and request_deadline_at <= budget_deadline:
            return "request_deadline_exceeded"
        return "budget_exhausted"

    @staticmethod
    def _classify_exception_termination_reason(exc: Exception) -> str:
        reason = getattr(exc, "reason", None)
        if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
            return "provider_timeout"
        if isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout):
            return "provider_timeout"
        if "timed out" in str(exc).lower():
            return "provider_timeout"
        return "provider_error"

    @staticmethod
    def _producer_query_terms(producer: str) -> List[str]:
        normalized = " ".join((producer or "").split()).strip()
        if not normalized:
            return []
        lowered = normalized.lower()
        stripped = re.sub(r"^(ys|domain|estate|winery)\s+", "", lowered, flags=re.IGNORECASE).strip()
        terms = [normalized]
        if stripped and stripped != lowered:
            terms.append(stripped.title())
        return terms
