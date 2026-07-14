import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...schemas.ai import AnalysisResult, Hit

FAIL_CLOSED_PROMPT_CATEGORIES = {
    "source_validation",
    "critic_score_lookup",
}
CRITIC_SOURCE_TOKENS = {
    "wine advocate",
    "jasper morris",
    "burghound",
    "vinous",
    "decanter",
    "critic",
    "score",
    "rating",
    "points",
}


class GroundingService:
    def post_process(
        self,
        *,
        query: str,
        answer: Dict[str, Any],
        hits: Sequence[Hit],
        analysis: AnalysisResult,
        language: Optional[str] = None,
        attachment: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_answer = dict(answer or {})
        citations = self._normalize_records(normalized_answer.get("citations"))
        hit_records = [self._hit_to_record(hit) for hit in hits]
        aligned_citations = self._filter_citations_by_hits(citations, hit_records)
        guarded_citations, guardrail_flags = self._apply_guardrails(aligned_citations, analysis)

        metadata = dict(normalized_answer.get("metadata") or {})
        response_mode = str(metadata.get("response_mode") or "").strip()
        missing_capabilities = list(metadata.get("missing_capabilities") or [])
        retrieval_errors = dict(metadata.get("retrieval_errors") or {})
        attachment_context = (
            analysis.attachment_context
            if isinstance(getattr(analysis, "attachment_context", None), dict)
            else {}
        )

        attachment_ingested = bool(attachment)
        if attachment:
            metadata["attachment"] = attachment
            if (
                attachment_context
                and str(attachment_context.get("status") or "").strip()
                not in {"analyzed", "analysis_partial"}
                and "attachment_understood_but_not_fully_processed" not in missing_capabilities
            ):
                missing_capabilities.append("attachment_understood_but_not_fully_processed")
            if attachment_context.get("status") == "analyzed":
                processing_state = "attachment_analyzed"
            elif attachment_context.get("status") == "analysis_partial":
                processing_state = "attachment_analysis_partial"
            else:
                processing_state = "metadata_only"
        elif analysis.prompt_category == "url_product_lookup":
            url_lookup = metadata.get("url_lookup") if isinstance(metadata.get("url_lookup"), dict) else {}
            availability_result = str(metadata.get("availability_result") or "").strip()
            parse_status = str(url_lookup.get("parse_status") or "").strip()
            if response_mode == "templated_url_product_lookup":
                if availability_result == "exact_match":
                    processing_state = "url_lookup_resolved_exact"
                elif availability_result == "near_match":
                    processing_state = "url_lookup_resolved_near"
                elif availability_result == "not_sold":
                    processing_state = "url_lookup_resolved_not_sold"
                elif parse_status == "failed":
                    processing_state = "url_lookup_parse_failed"
                else:
                    processing_state = "url_lookup_resolved_uncertain"
            else:
                processing_state = "url_lookup_pending"
        else:
            processing_state = "no_attachment"

        if len(aligned_citations) < len(citations):
            guardrail_flags.append("citation_mismatch_filtered")
            guardrail_flags.append("citation_hit_mismatch")

        answer_looks_non_assertive = self._looks_non_assertive_fallback(str(normalized_answer.get("text") or ""))
        if answer_looks_non_assertive and response_mode not in {
            "deterministic_grounded_fallback",
            "deterministic_no_hit_fallback",
            "critic_secondary_evidence_no_score",
            "answerable_with_gaps",
        }:
            guarded_citations = []
            retrieval_errors.setdefault("grounding", "Non-assertive fallback response does not retain citations.")

        fallback_applied = False
        if not guarded_citations:
            retrieval_errors.setdefault("grounding", "No grounded citations remained after guardrail filtering.")
            if self._should_fail_closed(analysis, metadata) and response_mode != "templated_url_product_lookup":
                normalized_answer["text"] = self._fallback_text(language)
                fallback_applied = True
                guardrail_flags.extend(["fail_closed", "missing_authoritative_source"])
        elif (
            self._should_fail_closed(analysis, metadata)
            and response_mode != "templated_url_product_lookup"
            and not self._has_reliable_authoritative_citations(guarded_citations, analysis)
        ):
            retrieval_errors.setdefault(
                "grounding",
                "Only low-confidence external citations remained after guardrail filtering.",
            )
            normalized_answer["text"] = self._fallback_text(language)
            guarded_citations = []
            fallback_applied = True
            guardrail_flags.extend(["fail_closed", "authoritative_quality_gate_failed", "missing_authoritative_source"])

        grounded_summary = self._build_grounded_summary(guarded_citations)
        grounded_highlights = self._build_grounded_highlights(guarded_citations)
        metadata["grounded_summary"] = grounded_summary
        metadata["grounded_highlights"] = grounded_highlights
        metadata["result_card_summary_points"] = self._build_result_card_summary_points(
            answer_text=str(normalized_answer.get("text") or ""),
            grounded_highlights=grounded_highlights,
        )
        metadata["source_tier"] = self._collect_source_tier(guarded_citations)
        metadata["confidence"] = self._confidence_label(guarded_citations, retrieval_errors)
        metadata["missing_capabilities"] = missing_capabilities
        metadata["retrieval_errors"] = retrieval_errors
        metadata["attachment_ingested"] = attachment_ingested
        metadata["processing_state"] = processing_state
        metadata["attachment_context"] = attachment_context
        metadata["attachment_summary"] = attachment_context.get("summary") if attachment_context else None
        metadata["attachment_entity_hints"] = attachment_context.get("entity_hints") if attachment_context else {}
        metadata["attachment_match_intent"] = attachment_context.get("match_intent") if attachment_context else None
        metadata["grounding"] = {
            "pre_guardrail_hit_count": len(aligned_citations),
            "post_guardrail_hit_count": len(guarded_citations),
            "fallback_applied": fallback_applied,
            "guardrail_flags": self._dedupe_flags(guardrail_flags),
        }
        metadata["citation_validation"] = {
            "input_citation_count": len(citations),
            "mapped_citation_count": len(aligned_citations),
            "post_guardrail_citation_count": len(guarded_citations),
            "unmapped_citation_count": max(len(citations) - len(aligned_citations), 0),
            "all_citations_mapped": len(citations) == len(aligned_citations),
        }
        non_assertive_response = bool(
            fallback_applied
            or answer_looks_non_assertive
            or (
                response_mode
                in {
                    "templated_fail_closed",
                    "templated_general_timeout",
                    "templated_internal_low_coverage",
                }
                and not guarded_citations
            )
        )
        metadata["hard_error_flags"] = self._build_hard_error_flags(
            guardrail_flags,
            non_assertive_response=non_assertive_response,
        )

        normalized_answer["citations"] = guarded_citations
        normalized_answer["metadata"] = metadata
        return normalized_answer

    def _should_fail_closed(self, analysis: AnalysisResult, metadata: Optional[Dict[str, Any]] = None) -> bool:
        metadata = metadata or {}
        source_policy = str(metadata.get("source_policy") or "").strip()
        prompt_category = str(metadata.get("prompt_category") or analysis.prompt_category or "").strip()
        if str(metadata.get("response_mode") or "").strip() == "critic_secondary_evidence_no_score":
            return False
        if str(metadata.get("response_mode") or "").strip() == "answerable_with_gaps":
            return False
        if (
            source_policy
            and source_policy != "authoritative_external_required"
            and prompt_category not in FAIL_CLOSED_PROMPT_CATEGORIES
        ):
            return False
        return bool(
            analysis.needs_authoritative_sources
            or prompt_category in FAIL_CLOSED_PROMPT_CATEGORIES
        )

    @staticmethod
    def _fallback_text(language: Optional[str]) -> str:
        if language == "zh-Hant":
            return "目前沒有足夠可驗證的可靠來源支撐這個答案，所以我不能確認或猜測。請縮小品牌、產品、型號、分類或指定可查證來源後再試。"
        return "I do not have enough grounded citations to answer this reliably. Please narrow the query or provide clearer brand, product, category, or source constraints."

    @staticmethod
    def _looks_non_assertive_fallback(text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        markers = (
            "生成回覆時暫時遇到系統連線問題",
            "不會直接用未整理的來源片段補成答案",
            "目前沒有足夠且可對應的可靠引用來源",
            "沒有足夠可驗證的可靠來源",
            "無法穩健回答",
            "cannot verify",
            "will not guess",
            "not enough grounded citations",
            "not enough verifiable",
            "generation service timed out",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _hit_to_record(hit: Hit) -> Dict[str, Any]:
        return hit.model_dump() if isinstance(hit, Hit) else dict(hit or {})

    @staticmethod
    def _normalize_records(records: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for record in records or []:
            if isinstance(record, dict):
                normalized.append(dict(record))
        return normalized

    def _filter_citations_by_hits(
        self,
        citations: List[Dict[str, Any]],
        hits: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not citations or not hits:
            return []
        hit_keys = {self._identity(hit) for hit in hits if not self._identity_is_empty(self._identity(hit))}
        filtered: List[Dict[str, Any]] = []
        for citation in citations:
            identity = self._identity(citation)
            if not self._identity_is_empty(identity) and identity in hit_keys:
                filtered.append(citation)
        return filtered

    def _apply_guardrails(
        self,
        citations: List[Dict[str, Any]],
        analysis: AnalysisResult,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        guarded = list(citations)
        flags: List[str] = []
        producer_hint = self._normalize_hint(analysis.entity_hints.get("producer"))
        if (analysis.prompt_category or "") == "producer_ranking":
            producer_hint = None
        if (analysis.prompt_category or "") in {"book_corpus_lookup", "internal_rag_only_validation"}:
            producer_hint = None
        if (analysis.prompt_category or "") == "inventory_lookup" and self._looks_like_broad_inventory_prompt(producer_hint):
            producer_hint = None
        if (analysis.prompt_category or "") in {"inventory_lookup", "source_hierarchy_conflict"} and self._looks_like_broad_vintage_or_region_prompt(producer_hint):
            producer_hint = None
        if (analysis.prompt_category or "") == "inventory_lookup" and self._looks_like_style_descriptor_hint(producer_hint):
            producer_hint = None
        region_hint = self._normalize_hint(analysis.entity_hints.get("region"))
        region_guardrail_strict = self._should_apply_strict_region_guardrail(analysis, producer_hint)

        if producer_hint and guarded:
            matches = [citation for citation in guarded if self._record_mentions(citation, producer_hint)]
            if len(matches) < len(guarded):
                flags.append("entity_guardrail_filtered")
            if matches or self._should_fail_closed(analysis):
                guarded = matches
            elif not matches:
                flags.append("entity_mismatch")

        if region_hint and region_guardrail_strict and guarded:
            matches = [citation for citation in guarded if self._record_mentions(citation, region_hint, region_mode=True)]
            if len(matches) < len(guarded):
                flags.append("region_guardrail_filtered")
            if matches or self._should_fail_closed(analysis):
                guarded = matches
            elif not matches:
                flags.append("region_mismatch")

        return guarded, self._dedupe_flags(flags)

    @staticmethod
    def _should_apply_strict_region_guardrail(
        analysis: AnalysisResult,
        producer_hint: Optional[str],
    ) -> bool:
        if producer_hint:
            return True
        if analysis.needs_authoritative_sources:
            return True
        return (analysis.prompt_category or "") in FAIL_CLOSED_PROMPT_CATEGORIES

    @staticmethod
    def _looks_like_broad_inventory_prompt(value: Optional[str]) -> bool:
        if not value:
            return False
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", value.lower())
        if len(tokens) <= 4:
            return False
        broad_markers = {
            "customer",
            "asks",
            "whether",
            "inventory",
            "balanced",
            "sales",
            "answer",
            "current",
            "review",
            "data",
        }
        return any(token in broad_markers for token in tokens)

    @staticmethod
    def _looks_like_broad_vintage_or_region_prompt(value: Optional[str]) -> bool:
        if not value:
            return False
        lowered = value.lower()
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", lowered)
        if re.fullmatch(r"(?:19|20)\d{2}\s+(?:red|white)?\s*(?:burgundy|bourgogne)", lowered):
            return True
        has_vintage = any(re.fullmatch(r"(?:19|20)\d{2}", token) for token in tokens)
        has_region = any(token in {"burgundy", "bourgogne", "champagne", "bordeaux"} for token in tokens)
        has_style = any(token in {"red", "white", "vintage", "wine", "wines"} for token in tokens)
        return has_vintage and has_region and has_style

    @staticmethod
    def _looks_like_style_descriptor_hint(value: Optional[str]) -> bool:
        if not value:
            return False
        tokens = re.findall(r"[a-z0-9\u4e00-\u9fff]+", value.lower())
        if not tokens:
            return False
        style_tokens = {
            "red",
            "white",
            "rose",
            "sparkling",
            "well",
            "balanced",
            "classic",
            "elegant",
            "light",
            "lighter",
            "fresh",
            "cool",
            "cooler",
            "ripe",
            "weak",
            "structured",
        }
        return all(token in style_tokens for token in tokens)

    @staticmethod
    def _normalize_hint(value: Any) -> Optional[str]:
        if isinstance(value, list):
            for item in value:
                normalized = GroundingService._normalize_hint(item)
                if normalized:
                    return normalized
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "bourgogne":
                return "burgundy"
            return normalized or None
        return None

    def _record_mentions(self, record: Dict[str, Any], hint: str, *, region_mode: bool = False) -> bool:
        haystack = " ".join(
            filter(
                None,
                [
                    str(record.get("text") or ""),
                    str(record.get("summary") or ""),
                    self._meta_to_text(record.get("meta") or {}),
                ],
            )
        ).lower()
        if not haystack:
            return False
        candidates = [hint]
        if region_mode and hint == "burgundy":
            candidates.append("bourgogne")
        if "saint" in hint:
            candidates.append(hint.replace("saint", "st"))
            candidates.append(hint.replace("saint", "st."))
        if re.search(r"\bst\b", hint):
            candidates.append(re.sub(r"\bst\.?\b", "saint", hint))
        if any(candidate in haystack for candidate in candidates):
            return True
        tokens = self._meaningful_tokens(hint)
        if tokens and all(self._token_matches_haystack(token, haystack) for token in tokens):
            return True
        return False

    def _meta_to_text(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._meta_to_text(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(self._meta_to_text(item) for item in value)
        return str(value or "")

    @staticmethod
    def _meaningful_tokens(value: str) -> List[str]:
        stop_words = {
            "la",
            "le",
            "les",
            "de",
            "des",
            "du",
            "and",
            "the",
            "ys",
            "domain",
            "maison",
            "chateau",
            "château",
            "estate",
            "winery",
        }
        tokens = [
            token
            for token in re.split(r"[^a-z0-9]+", (value or "").lower())
            if len(token) > 1 and token not in stop_words
        ]
        deduped: List[str] = []
        for token in tokens:
            if token not in deduped:
                deduped.append(token)
        return deduped

    @staticmethod
    def _token_matches_haystack(token: str, haystack: str) -> bool:
        if token in haystack:
            return True
        if token == "saint":
            return bool(re.search(r"\bst\.?\b", haystack))
        if token == "st":
            return "saint" in haystack
        return False

    @staticmethod
    def _identity(record: Dict[str, Any]) -> Tuple[str, str, str, str]:
        meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
        return (
            str(record.get("id") or ""),
            str(record.get("document_id") or ""),
            str(record.get("chunk_idx") or ""),
            str(record.get("filename") or meta.get("filename") or meta.get("url") or ""),
        )

    @staticmethod
    def _identity_is_empty(identity: Tuple[str, str, str, str]) -> bool:
        return not any(str(item or "").strip() for item in identity)

    @staticmethod
    def _first_non_empty(*values: str) -> str:
        for value in values:
            normalized = " ".join((value or "").split())
            if normalized:
                return normalized
        return ""

    def _build_grounded_summary(self, citations: List[Dict[str, Any]]) -> str:
        if not citations:
            return ""
        top = citations[0]
        summary = self._first_non_empty(
            str(top.get("summary") or ""),
            str(top.get("text") or ""),
        )
        return summary[:220].rstrip()

    def _build_grounded_highlights(self, citations: List[Dict[str, Any]]) -> List[str]:
        highlights: List[str] = []
        for citation in citations:
            candidate = self._first_non_empty(
                str(citation.get("summary") or ""),
                str(citation.get("text") or ""),
            )
            if not candidate or candidate in highlights:
                continue
            highlights.append(candidate[:220].rstrip())
            if len(highlights) >= 4:
                break
        return highlights

    @staticmethod
    def _normalize_summary_line(value: str) -> str:
        return " ".join((value or "").split()).strip(" -•\t")

    @classmethod
    def _is_low_signal_summary_line(cls, value: str) -> bool:
        normalized = cls._normalize_summary_line(value)
        if not normalized:
            return True
        lowered = normalized.lower()
        if normalized.startswith(("以下以", "內容以", "補充建議", "若您需要", "如需我", "未來可查證", "已知理念")):
            return True
        if lowered.startswith((
            "below is",
            "content is based on",
            "if you need",
            "supplementary note",
            "additional note",
        )):
            return True
        return False

    @classmethod
    def _clip_summary_line(cls, value: str, max_length: int = 72) -> str:
        normalized = cls._normalize_summary_line(value)
        if len(normalized) <= max_length:
            return normalized
        return normalized[:max_length].rstrip() + "..."

    @classmethod
    def _strip_section_heading(cls, value: str) -> str:
        normalized = cls._normalize_summary_line(value)
        normalized = re.sub(r"^\d+\s*[.)、]\s*", "", normalized)
        normalized = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", normalized)
        return normalized.strip()

    @classmethod
    def _build_section_summary_points(cls, answer_text: str) -> List[str]:
        raw_lines = [line.strip() for line in str(answer_text or "").splitlines() if line.strip()]
        if not raw_lines:
            return []
        sections: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for line in raw_lines:
            if re.match(r"^\d+\s*[.)、]\s*", line):
                current = {"heading": cls._strip_section_heading(line), "details": []}
                sections.append(current)
                continue
            if current is None:
                continue
            if re.match(r"^[-•●]\s*", line):
                detail = cls._normalize_summary_line(re.sub(r"^[-•●]\s*", "", line))
                if detail and not cls._is_low_signal_summary_line(detail):
                    current["details"].append(detail)
                continue
            if not cls._is_low_signal_summary_line(line):
                current["details"].append(cls._normalize_summary_line(line))

        points: List[str] = []
        for section in sections:
            heading = cls._strip_section_heading(str(section.get("heading") or ""))
            detail = ""
            for item in section.get("details") or []:
                if not cls._is_low_signal_summary_line(item):
                    detail = cls._clip_summary_line(item)
                    break
            if heading and detail:
                points.append(f"{heading}：{detail}")
            if len(points) >= 3:
                break
        return points

    @classmethod
    def _build_result_card_summary_points(
        cls,
        *,
        answer_text: str,
        grounded_highlights: List[str],
    ) -> List[str]:
        section_points = cls._build_section_summary_points(answer_text)
        section_points = [point.replace("嚗", "\uff1a") for point in section_points]
        if section_points:
            return section_points[:3]

        points: List[str] = []
        for item in grounded_highlights or []:
            normalized = cls._clip_summary_line(item)
            if not normalized or cls._is_low_signal_summary_line(normalized) or normalized in points:
                continue
            points.append(normalized)
            if len(points) >= 3:
                break
        return points

    @staticmethod
    def _collect_source_tier(citations: List[Dict[str, Any]]) -> List[str]:
        tiers: List[str] = []
        for citation in citations:
            tier = citation.get("source_tier")
            if not tier and isinstance(citation.get("meta"), dict):
                tier = citation["meta"].get("source_tier")
            if isinstance(tier, str) and tier and tier not in tiers:
                tiers.append(tier)
        return tiers

    @staticmethod
    def _confidence_label(citations: List[Dict[str, Any]], retrieval_errors: Dict[str, Any]) -> str:
        if not citations:
            return "low"
        if retrieval_errors:
            return "medium"
        if len(citations) >= 2:
            return "high"
        return "medium"

    @staticmethod
    def _has_reliable_authoritative_citations(
        citations: List[Dict[str, Any]],
        analysis: Optional[AnalysisResult] = None,
    ) -> bool:
        for citation in citations:
            source_tier = str(
                citation.get("source_tier")
                or (citation.get("meta") or {}).get("source_tier")
                or ""
            ).strip()
            source_type = str(citation.get("source_type") or "").strip()
            if getattr(analysis, "prompt_category", None) == "critic_score_lookup":
                if source_tier not in {"Tier 1", "Tier 2", "external_evidence"}:
                    continue
                text = " ".join(
                    str(value or "")
                    for value in (
                        citation.get("text"),
                        citation.get("summary"),
                        GroundingService._meta_to_text_static(citation.get("meta") or {}),
                    )
                ).lower()
                if not any(token in text for token in CRITIC_SOURCE_TOKENS):
                    continue
                return True
            if source_tier in {"Tier 1", "Tier 2", "internal", "internal_primary", "internal_official", "internal_approved", "internal_inventory", "external_evidence"}:
                return True
            if source_type and source_type != "external":
                return True
        return False

    @staticmethod
    def _meta_to_text_static(value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(GroundingService._meta_to_text_static(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return " ".join(GroundingService._meta_to_text_static(item) for item in value)
        return str(value or "")

    @staticmethod
    def _build_hard_error_flags(
        guardrail_flags: List[str],
        *,
        non_assertive_response: bool = False,
    ) -> List[str]:
        mapped: List[str] = []
        flag_set = set(guardrail_flags or [])
        if (
            not non_assertive_response
            and ("citation_hit_mismatch" in flag_set or "citation_mismatch_filtered" in flag_set)
        ):
            mapped.append("wrong_citation")
        if not non_assertive_response and "entity_mismatch" in flag_set:
            mapped.append("wrong_entity")
        if not non_assertive_response and "region_mismatch" in flag_set:
            mapped.append("wrong_region")
        if "missing_authoritative_source" in flag_set or "authoritative_quality_gate_failed" in flag_set:
            mapped.append("missing_source")
        return GroundingService._dedupe_flags(mapped)

    @staticmethod
    def _dedupe_flags(flags: List[str]) -> List[str]:
        deduped: List[str] = []
        for flag in flags:
            if flag and flag not in deduped:
                deduped.append(flag)
        return deduped
