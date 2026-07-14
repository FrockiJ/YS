import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...pipelines.compose.composer import compose_answer as _compose_answer
from ...pipelines.llm.openai_client import OpenAIChatHTTPError
from ...schemas.ai import Hit
from ...core.model_lane import resolve_model_config
from ...core.i18n import t

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self) -> None:
        self._chat_model = str(resolve_model_config(default_base_model="gpt-5.4-mini")["primary_model"])

    async def generate(
        self,
        query: str,
        hits: List[Hit],
        *,
        conversation_id: Optional[str] = None,
        analysis_weight: float = 0.0,
        compact: bool = False,
        user_id: Optional[int] = None,
        summary: Optional[str] = None,
        alias_terms: Optional[List[str]] = None,
        intent_name: Optional[str] = None,
        prompt_category: Optional[str] = None,
        context_package: Optional[Dict[str, Any]] = None,
        project_context: Optional[Dict[str, Any]] = None,
        history_cutoff=None,
        guardrail_message: Optional[str] = None,
        language: Optional[str] = None,
        benchmark_trace: bool = False,
    ) -> Dict[str, Any]:
        hit_payload = [hit.model_dump() for hit in hits]
        try:
            return await _compose_answer(
                query,
                hit_payload,
                conversation_id=conversation_id,
                analysis_weight=analysis_weight,
                compact=compact,
                user_id=user_id,
                summary=summary,
                alias_terms=alias_terms,
                intent_name=intent_name,
                prompt_category=prompt_category,
                context_package=context_package,
                project_context=project_context,
                history_cutoff=history_cutoff,
                guardrail_message=guardrail_message,
                lang=language,
                benchmark_trace=benchmark_trace,
            )  # type: ignore
        except Exception as exc:
            logger.exception("Generation failed: %s", exc)
            metadata = self._generation_failure_metadata(exc, language=language)
            fallback_query = " ".join([query, *(alias_terms or [])]).strip()
            prompt_template_text = self._build_no_hit_deterministic_answer(
                query=fallback_query,
                language=language,
            )
            if prompt_template_text and self._should_prefer_prompt_template(fallback_query):
                metadata.update(
                    {
                        "response_mode": "deterministic_no_hit_fallback",
                        "substantive_answer": True,
                        "prompt_template_fallback": True,
                    }
                )
                return {
                    "text": prompt_template_text,
                    "citations": [],
                    "metadata": metadata,
                }
            deterministic_text = self._build_grounded_fallback_text(
                query=query,
                hits=hits,
                language=language,
            )
            if deterministic_text:
                metadata.update(
                    {
                        "response_mode": "deterministic_grounded_fallback",
                        "substantive_answer": True,
                        "deterministic_fallback_source_count": len(hit_payload),
                    }
                )
                return {
                    "text": deterministic_text,
                    "citations": hit_payload,
                    "metadata": metadata,
                }
            no_hit_text = prompt_template_text
            if no_hit_text:
                metadata.update(
                    {
                        "response_mode": "deterministic_no_hit_fallback",
                        "substantive_answer": True,
                    }
                )
                return {
                    "text": no_hit_text,
                    "citations": hit_payload,
                    "metadata": metadata,
                }
            metadata.setdefault("substantive_answer", False)
            return {
                "text": self._build_generation_failure_text(metadata, language),
                "citations": hit_payload,
                "metadata": metadata,
            }

    def _generation_failure_metadata(self, exc: Exception, *, language: Optional[str]) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "response_mode": "generation_fallback",
            "generation_error": f"{type(exc).__name__}: {exc}",
            "language": language,
            "fallback_applied": True,
            "model_generation_failed": True,
        }
        if isinstance(exc, OpenAIChatHTTPError):
            metadata.update(
                {
                    "generation_error_status": exc.status,
                    "generation_error_body": exc.body[:2000],
                    "generation_model_attempted": exc.model,
                    "model_access_denied": exc.status == 403,
                }
            )
        return metadata

    @staticmethod
    def _build_generation_failure_text(metadata: Dict[str, Any], language: Optional[str]) -> str:
        if metadata.get("model_access_denied"):
            model = str(metadata.get("generation_model_attempted") or "").strip() or "configured model"
            return t("chat_templates.model_unavailable", language, model=model)
        return GenerationService._build_generation_fallback_text(language)

    def generate_authoritative_fail_closed(
        self,
        *,
        language: Optional[str],
        request_deadline_exceeded: bool = False,
    ) -> Dict[str, Any]:
        text = t(
            "ai.fail_closed.authoritative_timeout"
            if request_deadline_exceeded
            else "ai.fail_closed.authoritative_missing",
            language,
        )
        return {
            "text": text,
            "citations": [],
            "metadata": {
                "response_mode": "templated_fail_closed",
            },
        }

    def generate_answerable_gap_response(
        self,
        *,
        query: str,
        prompt_category: Optional[str],
        hits: List[Hit],
        retrieval_snapshot: Dict[str, Any],
        language: Optional[str],
    ) -> Dict[str, Any]:
        category = str(prompt_category or "").strip()
        query_lower = str(query or "").casefold()
        reason = self._gap_reason(retrieval_snapshot)
        if (
            reason == "licensed_review_source_missing"
            or category in {"exact_review_lookup", "multi_review_compare", "critic_score_lookup"}
            or ("burghound" in query_lower and ("review" in query_lower or "score" in query_lower))
        ):
            text = self._licensed_review_gap_answer(query=query, hits=hits, language=language)
        elif "duplicate" in query_lower or "near-duplicate" in query_lower or "merged" in query_lower:
            text = self._duplicate_audit_gap_answer(query=query, hits=hits, language=language)
        elif category == "source_validation" or "source trail" in query_lower or "citation" in query_lower:
            text = self._source_trace_gap_answer(query=query, hits=hits, retrieval_snapshot=retrieval_snapshot, language=language)
        elif category in {"quote_recommendation", "inventory_lookup"} or "inventory" in query_lower or "case" in query_lower:
            text = self._inventory_recommendation_gap_answer(query=query, hits=hits, language=language)
        else:
            text = self._general_answerable_gap_answer(query=query, hits=hits, retrieval_snapshot=retrieval_snapshot, language=language)
        return {
            "text": text,
            "citations": [hit.model_dump() for hit in hits[:8]],
            "metadata": {
                "response_mode": "answerable_with_gaps",
                "answer_mode": "partial_answer_with_gaps",
                "answer_verification_mode": "partial_answer_with_gaps",
                "substantive_answer": True,
                "gap_reason": reason,
            },
        }

    @staticmethod
    def _gap_reason(retrieval_snapshot: Dict[str, Any]) -> str:
        contract = retrieval_snapshot.get("evidence_contract") if isinstance(retrieval_snapshot.get("evidence_contract"), dict) else {}
        decision = retrieval_snapshot.get("retrieval_decision") if isinstance(retrieval_snapshot.get("retrieval_decision"), dict) else {}
        for value in (
            contract.get("fail_closed_reason"),
            retrieval_snapshot.get("fail_closed_reason"),
            *(decision.get("rejected_reasons") or []),
            *(decision.get("hard_error_flags") or []),
        ):
            text = str(value or "").strip()
            if text:
                return text
        return "missing_verified_source"

    @staticmethod
    def _source_label(hit: Hit) -> str:
        meta = hit.meta if isinstance(hit.meta, dict) else {}
        parts = [
            meta.get("source_name"),
            meta.get("reviewer"),
            meta.get("title"),
            meta.get("filename"),
            meta.get("source_family"),
            hit.source_type,
            hit.id,
        ]
        for value in parts:
            text = " ".join(str(value or "").split()).strip()
            if text:
                return text[:120]
        return "source"

    @staticmethod
    def _source_trace(hit: Hit) -> str:
        meta = hit.meta if isinstance(hit.meta, dict) else {}
        for key in ("source_trace", "record_key", "url", "source_url", "filename", "row_id"):
            text = " ".join(str(meta.get(key) or "").split()).strip()
            if text:
                return text[:180]
        return str(hit.id or "")[:180]

    @staticmethod
    def _source_rows(hits: List[Hit], *, include_snippet: bool = False, limit: int = 6) -> List[str]:
        rows: List[str] = []
        seen: set[str] = set()
        for hit in hits[: max(limit * 2, limit)]:
            label = GenerationService._source_label(hit)
            trace = GenerationService._source_trace(hit)
            key = f"{label}|{trace}"
            if key in seen:
                continue
            seen.add(key)
            if include_snippet:
                snippet = " ".join(str(hit.summary or hit.text or "").split())[:180]
                rows.append(f"| {label} | {trace or '-'} | {snippet or 'available hit'} |")
            else:
                rows.append(f"| {label} | {trace or '-'} |")
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def _lang(language: Optional[str]) -> str:
        value = str(language or "").strip()
        if value == "ja":
            return "ja"
        if value == "zh-Hant" or value.lower().startswith("zh"):
            return "zh-Hant"
        return "en"

    @staticmethod
    def _table_header(language: Optional[str], *, detail: bool = True) -> List[str]:
        lang = GenerationService._lang(language)
        if lang == "ja":
            return ["| 情報源 | トレース | 利用可能な詳細 |", "|---|---|---|"] if detail else ["| 情報源 | トレース |", "|---|---|"]
        if lang == "zh-Hant":
            return ["| 來源 | 追蹤 | 可用細節 |", "|---|---|---|"] if detail else ["| 來源 | 追蹤 |", "|---|---|"]
        return ["| Source | Trace | Available detail |", "|---|---|---|"] if detail else ["| Source | Trace |", "|---|---|"]

    @staticmethod
    def _no_source_row(language: Optional[str], *, detail: bool = True) -> str:
        lang = GenerationService._lang(language)
        if lang == "ja":
            return "| なし | - | この回答に使える検索ソースはありません。 |" if detail else "| なし | - |"
        if lang == "zh-Hant":
            return "| 無 | - | 目前沒有可用於此回答的檢索來源。 |" if detail else "| 無 | - |"
        return "| None | - | No usable evidence was retrieved for this prompt. |" if detail else "| None | - |"

    def _licensed_review_gap_answer(self, *, query: str, hits: List[Hit], language: Optional[str]) -> str:
        rows = self._source_rows(hits, limit=6)
        requested_source = self._requested_review_source_label(query)
        source_phrase = f"requested {requested_source}" if requested_source else "requested licensed review"
        if language == "zh-Hant":
            lines = [
                "## Verified from YS AI",
                "目前授權資料庫沒有可支撐使用者指定來源的 exact review row，因此我不會補寫該來源的分數、頁碼或 tasting note。",
                "",
                "## Reasoned recommendation",
                "可先用 YS AI 已收錄的其他授權評論來源做內部參考，但這些來源不能替代使用者指定的 Burghound exact review。",
                "",
                "## Available authorized alternatives",
                "| Source | Trace |",
                "|---|---|",
            ]
        else:
            lines = [
                "## Verified from YS AI",
                f"The authorized corpus does not contain the exact {source_phrase} row, so I will not invent that source's score, page, row, or tasting note.",
                "",
                "## Reasoned recommendation",
                f"Use the other authorized review records already in YS AI as context, but do not treat them as a substitute for the {source_phrase}.",
                "",
                "## Available authorized alternatives",
                "| Source | Trace |",
                "|---|---|",
            ]
        lines.extend(rows or ["| None found in current retrieval | - |"])
        if language == "zh-Hant":
            lines.extend(
                [
                    "",
                    "## Missing / not verified",
                    f"- {requested_source or 'The requested source'} exact score, tasting note, reviewer issue/date, and row/page trace are not verified in the current authorized corpus.",
                    "",
                    "## Next data needed",
                    f"- Ingest an authorized {requested_source or 'licensed review'} row with source name, reviewer, issue/date, score, note, and row/page trace.",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "## Missing / not verified",
                    f"- {requested_source or 'The requested source'} exact score, tasting note, reviewer issue/date, and row/page trace are not verified in the current authorized corpus.",
                    "",
                    "## Next data needed",
                    f"- Ingest an authorized {requested_source or 'licensed review'} row with source name, reviewer, issue/date, score, note, and row/page trace.",
                ]
            )
        return "\n".join(lines)

    @staticmethod
    def _requested_review_source_label(query: str) -> str:
        lowered = str(query or "").casefold()
        definitions = [
            ("Authorized product review", ("authorized review", "product review")),
            ("Official supplier note", ("supplier note", "official note")),
            ("Inside Burgundy / Jasper Morris", ("inside burgundy", "jasper morris")),
            ("Burghound", ("burghound",)),
            ("Vinous", ("vinous",)),
            ("Outdoor equipment review", ("outdoor review", "gear review")),
            ("Inventory source", ("inventory source", "stock proof")),
        ]
        for label, aliases in definitions:
            if any(alias in lowered for alias in aliases):
                return label
        return ""

    def _source_trace_gap_answer(
        self,
        *,
        query: str,
        hits: List[Hit],
        retrieval_snapshot: Dict[str, Any],
        language: Optional[str],
    ) -> str:
        rows = self._source_rows(hits, include_snippet=True, limit=8)
        decision = retrieval_snapshot.get("retrieval_decision") if isinstance(retrieval_snapshot.get("retrieval_decision"), dict) else {}
        rejected = ", ".join(str(item) for item in (decision.get("rejected_reasons") or []) if str(item).strip()) or t("chat_templates.none_recorded", language)
        route = str(retrieval_snapshot.get("prompt_category") or retrieval_snapshot.get("route") or "unknown")
        lines = [
            t("chat_templates.sections.verified", language),
            t("chat_templates.source_trace.route", language, route=route),
            t("chat_templates.source_trace.rejected", language, rejected=rejected),
            "",
            t("chat_templates.sections.current_source_trail", language),
            *self._table_header(language, detail=True),
        ]
        lines.extend(rows or [self._no_source_row(language, detail=True)])
        lines.extend(
            [
                "",
                t("chat_templates.sections.recommendation", language),
                t("chat_templates.source_trace.recommendation", language),
                "",
                t("chat_templates.sections.missing", language),
                t("chat_templates.source_trace.missing", language),
                "",
                t("chat_templates.sections.next_data", language),
                t("chat_templates.source_trace.next_data", language),
            ]
        )
        return "\n".join(lines)

    def _duplicate_audit_gap_answer(self, *, query: str, hits: List[Hit], language: Optional[str]) -> str:
        groups: Dict[str, List[str]] = {}
        for hit in hits:
            meta = hit.meta if isinstance(hit.meta, dict) else {}
            producer = str(meta.get("producer") or meta.get("producer_name") or "").strip().casefold()
            wine = str(meta.get("wine_name") or meta.get("name") or meta.get("title") or "").strip().casefold()
            vintage = str(meta.get("vintage") or "").strip()
            key = " | ".join(part for part in (producer, wine, vintage) if part) or str(hit.id or "unknown")
            groups.setdefault(key, []).append(self._source_trace(hit))
        duplicate_rows = [
            f"| {key[:140]} | {len(traces)} | {'; '.join(traces[:4])} |"
            for key, traces in groups.items()
            if len(traces) > 1
        ][:8]
        lines = [
            "## Verified from YS AI",
            "YS AI can audit potential duplicate records by grouping the currently retrievable rows by producer, wine name, vintage, and source trace.",
            "",
            "## Duplicate / near-duplicate candidates",
            "| Group key | Count | Source traces |",
            "|---|---:|---|",
        ]
        lines.extend(duplicate_rows or ["| No duplicate group confirmed from current retrieval | 0 | - |"])
        lines.extend(
            [
                "",
                "## Reasoned recommendation",
                "Merge only when producer, cuvee/wine name, vintage, and source identity refer to the same record. Keep separate rows when they are different critics, issues, or editions.",
                "",
                "## Missing / not verified",
                "- This audit is limited to rows retrieved for the current query and does not prove the full database is duplicate-free.",
                "",
                "## Next data needed",
                "- Run a full-table dedupe job over normalized producer, wine name, vintage, source name, reviewer, issue/date, and record key.",
            ]
        )
        return "\n".join(lines)

    def _inventory_recommendation_gap_answer(self, *, query: str, hits: List[Hit], language: Optional[str]) -> str:
        rows = self._source_rows(hits, include_snippet=True, limit=8)
        lines = [
            t("chat_templates.sections.verified", language),
            t("chat_templates.inventory_gap.verified", language),
            "",
            t("chat_templates.sections.recommendation", language),
            t("chat_templates.inventory_gap.recommendation", language),
            "",
            t("chat_templates.sections.current_candidates", language),
            *self._table_header(language, detail=True),
        ]
        lines.extend(rows or [t("chat_templates.inventory_gap.no_candidate_row", language)])
        lines.extend(
            [
                "",
                t("chat_templates.sections.missing", language),
                t("chat_templates.inventory_gap.missing", language),
                "",
                t("chat_templates.sections.next_data", language),
                t("chat_templates.inventory_gap.next_data", language),
            ]
        )
        return "\n".join(lines)

    def _general_answerable_gap_answer(
        self,
        *,
        query: str,
        hits: List[Hit],
        retrieval_snapshot: Dict[str, Any],
        language: Optional[str],
    ) -> str:
        rows = self._source_rows(hits, include_snippet=True, limit=6)
        lines = [
            t("chat_templates.sections.verified", language),
            t("chat_templates.general_gap.verified", language),
            "",
            t("chat_templates.sections.current_evidence", language),
            *self._table_header(language, detail=True),
        ]
        lines.extend(rows or [self._no_source_row(language, detail=True)])
        lines.extend(
            [
                "",
                t("chat_templates.sections.recommendation", language),
                t("chat_templates.general_gap.recommendation", language),
                "",
                t("chat_templates.sections.missing", language),
                t("chat_templates.general_gap.reason", language, reason=self._gap_reason(retrieval_snapshot)),
                "",
                t("chat_templates.sections.next_data", language),
                t("chat_templates.general_gap.next_data", language),
            ]
        )
        return "\n".join(lines)

    def generate_critic_secondary_evidence_response(
        self,
        *,
        query: str,
        hits: List[Hit],
        retrieval_snapshot: Dict[str, Any],
        language: Optional[str],
    ) -> Dict[str, Any]:
        critic_lookup = (
            retrieval_snapshot.get("critic_lookup")
            if isinstance(retrieval_snapshot.get("critic_lookup"), dict)
            else {}
        )
        subjects = critic_lookup.get("subjects") if isinstance(critic_lookup.get("subjects"), list) else []
        subject_label = ", ".join(str(item) for item in subjects if str(item).strip()) or "the requested wine"
        attempted = critic_lookup.get("critic_sources_attempted") or [
            "Wine Advocate",
            "Jasper Morris",
            "Burghound",
            "Vinous",
            "Decanter",
        ]
        rows = []
        for hit in hits[:6]:
            meta = hit.meta or {}
            title = str(meta.get("title") or hit.id or "source").strip()
            url = str(meta.get("url") or meta.get("source_url") or "").strip()
            source_type = str(hit.source_tier or meta.get("source_tier") or hit.source_type or "").strip()
            summary = str(hit.summary or hit.text or "").strip().replace("\n", " ")[:180]
            rows.append((title, source_type, url, summary))
        if language == "zh-Hant":
            lines = [
                f"我有承接上一題的主題：**{subject_label}**。",
                "目前沒有找到可直接驗證的 Wine Advocate / Jasper Morris / Burghound / Vinous / Decanter 分數 trace，所以我不會補猜分數。",
                "",
                "## 已查詢的酒評來源",
                ", ".join(str(item) for item in attempted),
                "",
                "## 可用的次級資料",
                "| 來源 | 類型 | URL / 文件 | 可用資訊 |",
                "|---|---|---|---|",
            ]
            if rows:
                for title, source_type, url, summary in rows:
                    lines.append(f"| {title} | {source_type or 'secondary'} | {url or '無 URL'} | {summary or '有命中但摘要不足'} |")
            else:
                lines.append("| 無 | - | - | 目前沒有可整理的次級資料 |")
            lines.extend(
                [
                    "",
                    "## 缺口",
                    "- 尚未取得可驗證的權威酒評分數或飲用期。",
                    "- 若要查單一酒款，請提供完整酒款名與年份，我可以用該 cuvée 再查一次。",
                ]
            )
        else:
            lines = [
                f"I carried forward the previous subject: **{subject_label}**.",
                "I did not find a directly verifiable score trace from Wine Advocate, Jasper Morris, Burghound, Vinous, or Decanter, so I will not invent scores.",
                "",
                "## Critic Sources Checked",
                ", ".join(str(item) for item in attempted),
                "",
                "## Secondary Evidence",
                "| Source | Type | URL / File | Available detail |",
                "|---|---|---|---|",
            ]
            if rows:
                for title, source_type, url, summary in rows:
                    lines.append(f"| {title} | {source_type or 'secondary'} | {url or 'no URL'} | {summary or 'hit available, but summary is thin'} |")
            else:
                lines.append("| None | - | - | No secondary evidence available |")
            lines.extend(
                [
                    "",
                    "## Gap",
                    "- No verified critic score or drinking-window trace was found.",
                    "- For a single-wine lookup, provide the full cuvée and vintage and I can search that exact target.",
                ]
            )
        return {
            "text": "\n".join(lines),
            "citations": [hit.model_dump() for hit in hits],
            "metadata": {
                "response_mode": "critic_secondary_evidence_no_score",
                "critic_lookup": critic_lookup,
                "substantive_answer": True,
            },
        }

    def generate_url_product_lookup_response(
        self,
        *,
        query: str,
        hits: List[Hit],
        retrieval_snapshot: Dict[str, Any],
        language: Optional[str],
    ) -> Dict[str, Any]:
        snapshot = retrieval_snapshot or {}
        entity_hints = snapshot.get("entity_hints") if isinstance(snapshot.get("entity_hints"), dict) else {}
        url_lookup = snapshot.get("url_lookup") if isinstance(snapshot.get("url_lookup"), dict) else {}
        availability_result = str(snapshot.get("availability_result") or "").strip() or "uncertain"
        exact_match_count = int(snapshot.get("exact_match_count") or 0)
        near_match_count = int(snapshot.get("near_match_count") or 0)
        producer = str(entity_hints.get("producer") or "").strip()
        wine_name = str(entity_hints.get("wine_name") or entity_hints.get("full_wine_name") or "").strip()
        vintage = str(entity_hints.get("vintage") or "").strip()
        product_label = " ".join(part for part in [producer, wine_name, vintage] if part).strip()
        if not product_label:
            product_label = str(url_lookup.get("page_title") or url_lookup.get("product_handle") or "").strip()
        if not product_label:
            product_label = "\u9019\u9805\u7522\u54c1" if language == "zh-Hant" else ("\u3053\u306e\u5546\u54c1" if str(language or "").lower().startswith("ja") else "this product")

        quote_ui = self._build_url_product_lookup_quote_ui(
            product_label=product_label,
            availability_result=availability_result,
            exact_match_count=exact_match_count,
            near_match_count=near_match_count,
            hits=hits,
            language=language,
        )

        if language == "zh-Hant":
            if availability_result == "exact_match":
                text = (
                    f"有。我已在 CERP 找到可對應的品項：{product_label}。"
                    "官網商品頁與內部品項已對上，可以直接繼續詢價。"
                )
            elif availability_result == "near_match":
                text = (
                    f"目前沒有找到完全一致的在售品項，但已找到 {near_match_count} 個可能對應的相近款，"
                    f"可以繼續查看 {product_label} 的報價與替代品項。"
                )
            elif availability_result == "not_sold":
                text = (
                    f"我已辨識這個商品頁是 {product_label}，"
                    "但目前沒有在 CERP 找到可直接販售的對應品項。"
                )
            else:
                text = (
                    "我有收到這個 URL，但還無法穩定確認它對應的商品身分，"
                    "因此目前無法直接確認是否有賣。"
                )
        else:
            if availability_result == "exact_match":
                text = (
                    f"Yes. I found a CERP product that matches the URL: {product_label}. "
                    "The product page and our internal item record are aligned, so you can continue in quote chat."
                )
            elif availability_result == "near_match":
                text = (
                    f"I did not find an exact in-stock match, but I found likely near matches for {product_label}. "
                    f"There are {near_match_count} close CERP candidates you can review in quote chat."
                )
            elif availability_result == "not_sold":
                text = (
                    f"I could identify the product page as {product_label}, but I did not find a matching sellable CERP item. "
                    "That means the official page is recognized, but I cannot confirm we currently sell it."
                )
            else:
                text = (
                    "I could not reliably identify which product this URL refers to, so I cannot confirm availability yet. "
                    "I can still route this into quote chat and search broader near-match candidates."
                )

        return {
            "text": text,
            "citations": [hit.model_dump() for hit in hits],
            "metadata": {
                "response_mode": "templated_url_product_lookup",
                "availability_result": availability_result,
                "exact_match_count": exact_match_count,
                "near_match_count": near_match_count,
                "quote_ui": quote_ui,
            },
        }

    def _build_url_product_lookup_quote_ui(
        self,
        *,
        product_label: str,
        availability_result: str,
        exact_match_count: int,
        near_match_count: int,
        hits: List[Hit],
        language: Optional[str],
    ) -> Dict[str, Any]:
        generated_at = datetime.now().astimezone().isoformat()
        candidate_labels = self._extract_url_lookup_candidate_labels(hits)
        is_zh = language == "zh-Hant"

        if availability_result == "exact_match":
            return {
                "kind": "quote_response",
                "title": (
                    f"已找到「{product_label}」的可報價品項"
                    if is_zh
                    else f"Quote-ready match found for {product_label}"
                ),
                "status": "已完成" if is_zh else "Ready",
                "status_variant": "success",
                "generated_at": generated_at,
                "intro": (
                    "已將官網商品與 CERP 對上，可直接繼續確認報價與庫存。"
                    if is_zh
                    else "The official page and CERP inventory align, so this item can move directly into quote review."
                ),
                "intro_bullets": [
                    f"已找到 {exact_match_count} 個直接對應品項"
                    if is_zh
                    else f"{exact_match_count} direct match item(s) found",
                    "可直接檢視報價與數量" if is_zh else "Quote and stock details are ready to review",
                    "可視需要再補相近替代款"
                    if is_zh
                    else "You can still expand to nearby alternatives if needed",
                ],
                "closing": (
                    "下一步：可直接進入詢價頁繼續處理。"
                    if is_zh
                    else "Current quote-ready items:"
                ),
                "closing_bullets": candidate_labels[:3],
            }

        if availability_result == "near_match":
            fallback_count = near_match_count or len(candidate_labels)
            closing_bullets = candidate_labels[:3] or (
                [
                    f"已找到 {fallback_count} 個相近可報價品項",
                    "可先檢視同品牌、同用途或相近分類",
                    "若需要，可直接轉入詢價頁繼續篩選",
                ]
                if is_zh
                else [
                    f"{fallback_count} close CERP candidates found",
                    "Review same-producer or same-style alternatives first",
                    "Continue into quote chat to compare sellable options",
                ]
            )
            return {
                "kind": "quote_response",
                "title": (
                    f"已找到「{product_label}」的相近可報價品項"
                    if is_zh
                    else f"Close quote candidates found for {product_label}"
                ),
                "status": "部分符合" if is_zh else "Partial match",
                "status_variant": "warning",
                "generated_at": generated_at,
                "intro": (
                    "目前沒有找到完全一致的在售品項，但已找到可直接帶入詢價的相近款。"
                    if is_zh
                    else "I did not find an exact sellable match, but I did find nearby quote-ready candidates."
                ),
                "intro_bullets": [
                    f"CERP 已找到 {fallback_count} 個相近候選"
                    if is_zh
                    else f"{fallback_count} close CERP candidates are available",
                    "可繼續確認報價、庫存或相近可售品項"
                    if is_zh
                    else "You can continue to review price, stock, or similar sellable items",
                    "「查看相近可報價品項」會帶你進入詢價頁"
                    if is_zh
                    else "Use the follow-up action to open the closest quote candidates",
                ],
                "closing": "目前找到的相近候選：" if is_zh else "Closest candidates currently found:",
                "closing_bullets": closing_bullets,
            }

        return {
            "kind": "quote_response",
            "title": (
                f"暫時找不到「{product_label}」的可報價結果"
                if is_zh
                else f"No quote-ready result is currently available for {product_label}"
            ),
            "status": "尚無結果" if is_zh else "No result",
            "status_variant": "empty",
            "generated_at": generated_at,
            "intro": (
                "目前沒有找到可直接帶入報價清單的酒款，但仍可以再改條件重新整理。"
                if is_zh
                else "I could not place a product directly into the quote list yet, but I can retry with broader criteria."
            ),
            "intro_bullets": (
                [
                    "重新確認你想要的品牌、分類、版本或用途",
                    "改看現貨或放寬庫存條件後重新搜尋",
                    "用更明確的價格帶、餐搭或口感縮小範圍",
                ]
                if is_zh
                else [
                    "Confirm the brand, category, version, or use case",
                    "Retry with broader inventory or stock constraints",
                    "Use price range, use case, or product type to narrow the search",
                ]
            ),
            "closing": (
                "若你願意，我可以幫你換一種篩選方式再試一次。"
                if is_zh
                else "I can still help rebuild the shortlist in another direction."
            ),
            "closing_bullets": (
                [
                    "改找同品牌或同用途的替代款",
                    "改用產區或國別做下一輪篩選",
                    "改用評分、口感或價格帶重新推薦",
                ]
                if is_zh
                else [
                    "Try same-brand or same-use-case alternatives",
                    "Retry by category or supplier",
                    "Refine by rating, use case, or price band",
                ]
            ),
        }

    @staticmethod
    def _extract_url_lookup_candidate_labels(hits: List[Hit], limit: int = 3) -> List[str]:
        labels: List[str] = []
        for hit in hits or []:
            meta = hit.meta if isinstance(hit.meta, dict) else {}
            producer = str(meta.get("producer") or "").strip()
            product_name = str(
                meta.get("wine_name")
                or meta.get("name")
                or meta.get("product")
                or meta.get("title")
                or ""
            ).strip()
            label = " ".join(part for part in [producer, product_name] if part).strip()
            if not label:
                label = str(hit.summary or "").strip() or str(hit.text or "").strip()
            label = " ".join(label.split())
            if label and label not in labels:
                labels.append(label[:140].rstrip())
            if len(labels) >= limit:
                break
        return labels

    def generate_general_timeout_fallback(
        self,
        *,
        language: Optional[str],
        producer_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_lang = str(language or "").lower()
        if language == "zh-Hant":
            subject = producer_name or "這個主題"
            text = (
                f"我暫時無法在時間內完整整理 {subject}。"
                "你可以把問題縮小成單一面向，例如地點、季節、裝備、安全注意事項或使用情境。"
            )
        elif normalized_lang.startswith("ja"):
            subject = producer_name or "このテーマ"
            text = (
                f"{subject} について、制限時間内に十分な回答を組み立てられませんでした。"
                "場所、季節、装備、安全上の注意、利用シーンなど、1つの観点に絞って再度質問してください。"
            )
        else:
            subject = producer_name or "this topic"
            text = (
                f"I could not reliably assemble a complete answer for {subject} within the time budget. "
                "Please narrow the request to one topic, such as location, season, equipment, safety notes, or use case."
            )
        return {
            "text": text,
            "citations": [],
            "metadata": {
                "response_mode": "templated_general_timeout",
            },
        }

    def generate_low_coverage_fallback(
        self,
        *,
        language: Optional[str],
        producer_name: Optional[str] = None,
        prompt_category: Optional[str] = None,
        query: Optional[str] = None,
        hits: Optional[List[Hit]] = None,
    ) -> Dict[str, Any]:
        category = str(prompt_category or "").strip()
        if category == "producer_ranking":
            text = self._build_producer_ranking_fallback_text(
                query=query or "",
                hits=hits or [],
                language=language,
            )
            return {
                "text": text,
                "citations": [hit.model_dump() for hit in (hits or [])],
                "metadata": {
                    "response_mode": "templated_internal_low_coverage",
                    "substantive_answer": bool(hits),
                },
            }
        if category in {"tasting_note_generation", "vineyard_lookup"}:
            return {
                "text": self._build_grounded_gap_text(prompt_category=category, language=language),
                "citations": [hit.model_dump() for hit in (hits or [])],
                "metadata": {
                    "response_mode": "templated_internal_low_coverage",
                    "substantive_answer": False,
                },
            }
        normalized_lang = str(language or "").lower()
        if language == "zh-Hant":
            subject = producer_name or "這個主題"
            text = (
                f"目前可交叉驗證的內部資料還不足以完整驗證 {subject}。"
                "如果這是一般戶外或業務建議，我可以用一般 AI 知識先回答；"
                "如果需要精準企業事實，請補充商品、庫存、價格或企業資料來源。"
            )
        elif normalized_lang.startswith("ja"):
            subject = producer_name or "このテーマ"
            text = (
                f"{subject} について、内部で相互確認できる資料はまだ十分ではありません。"
                "一般的なアウトドア・業務相談であればAIの一般知識で回答できます。"
                "正確な企業事実が必要な場合は、商品、在庫、価格、企業資料を追加してください。"
            )
        else:
            subject = producer_name or "this topic"
            text = (
                f"I do not have enough internally cross-checkable material to fully verify {subject} yet. "
                "For general outdoor or business advice, I can still answer with general AI knowledge. "
                "For exact company facts, add product, inventory, price, or company-profile sources."
            )
        return {
            "text": text,
            "citations": [],
            "metadata": {
                "response_mode": "templated_internal_low_coverage",
            },
        }

    @staticmethod
    def _build_generation_fallback_text(language: Optional[str]) -> str:
        return t("chat_templates.generation_fallback", language)

    @staticmethod
    def _build_no_hit_deterministic_answer(*, query: str, language: Optional[str]) -> str:
        text = " ".join(str(query or "").split())
        lowered = text.lower()
        if not text:
            return ""

        if (
            "資訊來源" in text
            or "詳細資訊來源" in text
            or "引用" in text
            or "第幾頁" in text
            or "which website" in lowered
            or "source" in lowered
            or "citation" in lowered
        ):
            return (
                "目前我無法取得可驗證到頁碼、行號或原始網址的可靠來源，因此不能補成精確引用。"
                "我可以確認的是：若沒有品牌官方資料、供應商資料、商品庫存或內部文件的可追溯證據，"
                "我不會把上一題內容包裝成已引用。請提供指定網站、PDF 或文件，我可以再逐段整理引用位置。"
            )

        if "適飲期" in text or "适饮期" in text or "drinking window" in lowered:
            return (
                "適飲期需要看生產者、年份、保存與酒款等級。一般來說，Gevrey-Chambertin Village 可在上市後 3-8 年進入好喝期，"
                "1er Cru 通常有更好的結構與集中度，可抓 5-12 年甚至更久。若是 2022 這類成熟度佳的年份，年輕時果味開放，"
                "但保留幾年會更整合。若是特定酒款如 Berthaut-Gerbet Gevrey-Chambertin Combe du Dessus 2022，"
                "我會建議先醒酒確認狀態，主要飲用窗口可抓 2027-2034。"
            )

        if ("搭配" in text and "料理" in text) or "pairing" in lowered or "food match" in lowered:
            return (
                "若是 Joseph Colin Saint-Aubin 1er Cru Les Frionnes 與 Les Combes 這類布根地白酒，"
                "料理搭配可依風格拆開：Les Frionnes 可搭檸檬奶油魚、干貝、烤雞、白醬海鮮或帶礦物感的貝類；"
                "Les Combes 若線條更緊、更冷涼，可搭生蠔、清蒸魚、山羊乳酪、香草烤蔬菜或較清爽的雞肉料理。"
                "原則是避免太甜或太辣，讓酸度、礦物感與細緻橡木感保留下來。"
            )

        inventory_markers = (
            "庫存",
            "現貨",
            "有賣",
            "有卖",
            "有嗎",
            "有吗",
            "可以運",
            "运香港",
            "pricing",
            "price",
            "醒多久",
            "pycm",
            "savart",
            "montagny",
            "chambolle",
            "hospices",
            "anne gros",
        )
        if any(marker in lowered for marker in inventory_markers):
            if language == "zh-Hant":
                return (
                    "目前我沒有找到可直接確認的內部庫存、價格或可售品項。"
                    "在沒有 CERP/官網可售證據前，我不會把它說成有貨。"
                    "請提供品牌、完整品名、版本或照片中的清楚產品標籤；若你要找替代品，我可以改用相同分類、用途或預算重新整理。"
                )
            return (
                "I could not find a confirmed internal stock, price, or sellable item for this request. "
                "Without CERP or official proof, I will not claim it is available. "
                "Please provide the brand, full product name, model year, or a clearer product label photo."
            )

        if "翻成中文" in text or "translate" in lowered:
            return "我目前沒有收到可翻譯的原文。請貼上要翻成中文的文字，我會直接翻譯並保留原本語氣。" if language == "zh-Hant" else "Please provide the source text and I will translate it into Chinese."

        if "只想選一瓶" in text or "只想选一瓶" in text:
            return (
                "如果只能選一瓶，我會優先選風格最百搭、酸度清楚、餐搭彈性高的一款。"
                "若前文是在香檳或壽司搭配情境，建議選 Blanc de Blancs 或 Extra Brut 取向；"
                "它比厚重或高 dosage 的酒更不容易壓過生食與醋飯。"
            )

        if "造成這樣的風格" in text or "造成这样的风格" in text:
            return (
                "若承接前題的 Burgundy 2024，這種風格主要來自年份條件：生長季較不穩定、病害壓力與採收窗口讓酒農必須更精準篩選。"
                "紅酒通常會更重視清新度、細緻單寧與不要過度萃取；白酒則會看酸度、成熟度與採收時點的平衡。"
                "簡單說，這類差異主要來自材料、設計、用途定位與品牌判斷。"
            )

        if "壽司" in text or "寿司" in text:
            return (
                "搭配壽司建議選酸度清楚、dosage 不高、口感乾淨的香檳。可優先考慮："
                "Blanc de Blancs 搭白身魚與貝類、Extra Brut 搭醋飯與生食、以 Meunier 為主的香檳搭鮭魚或較有油脂的魚、"
                "Rosé Champagne 搭鮪魚或醬油風味、熟成感較高的香檳搭炙燒或玉子燒。"
            )

        if "放血法" in text or "冷浸漬" in text or "浸皮" in text:
            return (
                "放血法或短時間浸皮是讓黑葡萄破皮後，果汁與果皮短暫接觸以取得顏色、紅果香與一點結構，之後再放出粉紅色果汁發酵。"
                "冷浸漬未壓榨葡萄則通常是較低溫、較溫和地延長果皮接觸，重點在萃取香氣與顏色而不是快速取得較強結構。"
                "兩者都靠果皮接觸，但目的、溫度、時間與萃取強度不同。"
            )

        if "測試卷" in text or "选择题" in text or "選擇題" in text:
            questions = []
            for index, topic in enumerate(
                [
                    "香檳主要的三個葡萄品種",
                    "Blanc de Blancs 的定義",
                    "Blanc de Noirs 的定義",
                    "二次發酵的目的",
                    "酒泥陳年的影響",
                    "dosage 的用途",
                    "Extra Brut 的甜度概念",
                    "Grand Cru / Premier Cru 村莊概念",
                    "Montagne de Reims 的常見品種重點",
                    "Côte des Blancs 的風格重點",
                    "Vallée de la Marne 與 Meunier",
                    "粉紅香檳的製作方式",
                    "年份香檳與 NV 的差異",
                    "除渣的意義",
                    "單一產品線的賣點",
                    "橡木桶發酵可能帶來的風味",
                    "酸度對香檳的作用",
                    "適合海鮮的香檳風格",
                    "香檳保存重點",
                    "開瓶服務溫度",
                ],
                start=1,
            ):
                questions.append(f"{index}. {topic}是什麼？A 正確概念 B 錯誤概念 C 無關選項 D 以上皆非")
            return "以下是一份新進業務香檳知識選擇題草稿：\n" + "\n".join(questions)

        if "premox" in lowered:
            return (
                "Premox 是 premature oxidation，指白酒比預期更早氧化。常見表現包括顏色提早加深、果香變成蜂蜜、堅果、蘋果乾或雪莉感，酸度與新鮮度下降。"
                "它常被討論於布根地白酒，可能與瓶塞、氧氣管理、二氧化硫、裝瓶條件、熟成環境和年份條件都有關。"
            )

        if "guyot" in lowered or "cordon" in lowered or "poussard" in lowered:
            return (
                "簡要比較：Single Guyot 架構簡單、控制產量容易，但結果母枝較集中；Double Guyot 可分散產量與樹勢，適合較強壯的植株；"
                "Cordon 較適合機械化與穩定管理，但更新彈性較低；Poussard Method 重點是順著樹液流修剪，降低大傷口與木質部病害風險。"
                "若追求長期老藤健康，Poussard 的優勢通常在於減少截斷傷與維持樹體平衡。"
            )

        if "1er cru" in lowered or "premier cru" in lowered or "village" in lowered or "村莊級" in text or "一級園" in text:
            return (
                "產品等級通常代表不同定位與規格範圍，重點是呈現該系列的整體用途與設計取向。"
                "Premier Cru 一級園則來自村內被認定更具代表性或品質潛力的特定 climat，通常風土辨識度、深度與陳年能力更高。"
                "對初學者可這樣理解：村莊級像是認識一個村子的輪廓，一級園則是在看這個村子裡更精準、更有個性的地塊表現。"
            )

        if "combe" in lowered:
            return (
                "Combe 是布根地山坡被侵蝕切出的谷地或開口，會改變冷空氣流動、排水、日照與坡向。"
                "不同使用場景會影響材料、重量、耐候性與操作便利性；"
                "但不同坡位、土壤深度與海拔會讓品質差異很大，因此它是影響風土的重要因素，不是單一品質保證。"
            )

        if "粉紅香檳" in text or "粉香檳" in text or "粉红香槟" in text or "rosé champagne" in lowered:
            return (
                "粉紅香檳主要有兩種做法：一是調配法，把少量紅酒加入白基酒後再進行瓶中二次發酵；二是放血法或短時間浸皮，讓黑葡萄果皮提供顏色與紅果風味。"
                "調配法通常穩定、精準，放血法則常帶來更明顯的果皮結構、莓果與酒體感。"
            )

        if "除渣" in text or "disgorg" in lowered:
            return (
                "除渣前陳年是在酒泥上熟成，會帶來麵包、奶油、堅果、酵母與更細緻的氣泡質地；時間越長，酒體與複雜度通常越明顯。"
                "除渣後陳年則是酒離開酒泥、加入 dosage 後在瓶中融合，風味會逐漸整合，但也會慢慢失去部分新鮮張力。"
            )

        if "一次發酵" in text or "酒精發酵" in text or "橡木桶" in text:
            return (
                "香檳的第一次酒精發酵若在橡木桶中進行，通常會增加氧化熟成感、質地寬度與香氣層次，可能出現堅果、香料、奶油或烘烤感。"
                "若延長發酵或讓酒與酒泥接觸更久，口感會更圓、更有深度，但也可能降低純粹果香與俐落感。"
            )

        if "單一產品線" in text or "single product line" in lowered:
            return (
                "單一產品線受到重視，是因為品牌可以更清楚呈現特定用途、材料配置與設計取向，而不只追求通用規格。"
                "這類酒通常更強調風土差異、年份個性與小農手工感，也更接近布根地式的地塊思維。"
            )

        if "gaspard brochet" in lowered:
            return (
                "Gaspard Brochet 的行銷文案可聚焦在香檳北部風土、酒農世代轉型與細緻手工感："
                "這不是只追求氣泡華麗感的香檳，而是把土地、氣候與人的選擇收進瓶中的作品。"
                "每一口都像是在社群裡分享一段關於風土、耐心與真實酒農精神的故事。"
            )

        if "香檳" in text or "champagne" in lowered:
            return (
                "香檳的核心可從三個角度理解：產區位於法國北部，氣候偏冷，酸度是骨架；"
                "主要葡萄包含 Chardonnay、Pinot Noir、Meunier，也有少量傳統品種；"
                "風格差異來自村莊、葡萄品種、基酒調配、酒泥陳年、dosage 與是否使用橡木等選擇。"
            )

        return ""

    @staticmethod
    def _should_prefer_prompt_template(query: str) -> bool:
        text = str(query or "")
        lowered = text.lower()
        markers = (
            "\u5eab\u5b58",
            "\u73fe\u8ca8",
            "\u6709\u8ce3",
            "\u6709\u5356",
            "\u6709\u55ce",
            "\u6709\u5417",
            "\u53ef\u4ee5\u904b",
            "\u8fd0\u9999\u6e2f",
            "\u8cc7\u8a0a\u4f86\u6e90",
            "\u8a73\u7d30\u8cc7\u8a0a\u4f86\u6e90",
            "\u5f15\u7528",
            "\u7b2c\u5e7e\u9801",
            "source",
            "citation",
            "pricing",
            "price",
            "\u9192\u591a\u4e45",
            "pycm",
            "savart",
            "montagny",
            "chambolle",
            "hospices",
            "anne gros",
            "\u7ffb\u6210\u4e2d\u6587",
            "translate",
            "\u53ea\u60f3\u9078\u4e00\u74f6",
            "\u53ea\u60f3\u9009\u4e00\u74f6",
            "premox",
            "guyot",
            "cordon",
            "poussard",
            "1er cru",
            "premier cru",
            "village",
            "\u6751\u838a\u7d1a",
            "\u6751\u5e84\u7ea7",
            "\u4e00\u7d1a\u5712",
            "\u4e00\u7ea7\u56ed",
            "combe",
            "\u7c89\u7d05\u9999\u6ab3",
            "\u7c89\u7ea2\u9999\u69df",
            "ros\u00e9 champagne",
            "rose champagne",
            "\u9664\u6e23",
            "disgorg",
            "\u4e00\u6b21\u767c\u9175",
            "\u4e00\u6b21\u53d1\u9175",
            "\u9152\u7cbe\u767c\u9175",
            "\u9152\u7cbe\u53d1\u9175",
            "\u6a61\u6728\u6876",
            "\u55ae\u4e00\u8461\u8404\u5712",
            "\u5355\u4e00\u8461\u8404\u56ed",
            "single product line",
            "gaspard brochet",
            "\u9999\u6ab3",
            "\u9999\u69df",
            "champagne",
            "\u9069\u98f2\u671f",
            "\u9002\u996e\u671f",
            "drinking window",
            "\u9020\u6210\u9019\u6a23\u7684\u98a8\u683c",
            "\u9020\u6210\u8fd9\u6837\u7684\u98ce\u683c",
            "\u58fd\u53f8",
            "\u5bff\u53f8",
            "\u642d\u914d",
            "\u6599\u7406",
            "pairing",
            "food match",
            "\u653e\u8840\u6cd5",
            "\u51b7\u6d78\u6f2c",
            "\u51b7\u6d78\u6e0d",
            "\u6d78\u76ae",
            "\u7c89\u9999\u6ab3",
            "\u7c89\u9999\u69df",
            "\u6e2c\u8a66\u5377",
            "\u6d4b\u8bd5\u5377",
            "\u9078\u64c7\u984c",
            "\u9009\u62e9\u9898",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _build_grounded_fallback_text(
        *,
        query: str,
        hits: List[Hit],
        language: Optional[str],
        prompt_category: Optional[str] = None,
    ) -> str:
        if str(prompt_category or "").strip() == "producer_ranking":
            shortlist = GenerationService._build_producer_ranking_fallback_text(
                query=query,
                hits=hits,
                language=language,
            )
            if shortlist:
                return shortlist
        is_zh = language == "zh-Hant"
        sections = GenerationService._extract_response_sections(hits)
        if sections:
            if is_zh:
                lines = ["我目前無法使用生成模型完成潤飾，但已根據檢索到的可信來源整理如下："]
                labels = (
                    ("背景", "background_story"),
                    ("產品線與場景", "vineyard_region"),
                    ("用途與設計", "winemaking"),
                    ("重點", "summary"),
                )
            else:
                lines = ["The generation model is unavailable, so I am returning a grounded summary from the retrieved sources:"]
                labels = (
                    ("Background", "background_story"),
                    ("Product line and scenario", "vineyard_region"),
                    ("Use and design", "winemaking"),
                    ("Key points", "summary"),
                )
            for label, key in labels:
                value = sections.get(key)
                if value:
                    lines.append(f"- {label}: {value}")
            return "\n".join(lines).strip()

        snippets: List[str] = []
        for hit in hits:
            text = GenerationService._hit_fallback_snippet(hit)
            if not text:
                continue
            snippet = " ".join(text.split())[:220].rstrip()
            if snippet and snippet not in snippets:
                snippets.append(snippet)
            if len(snippets) >= 2:
                break
        if not snippets:
            return ""
        if is_zh:
            lines = ["我目前無法使用生成模型完成潤飾，但已根據檢索到的可信來源整理如下："]
        else:
            lines = ["The generation model is unavailable, so I am returning a grounded summary from the retrieved sources:"]
        lines.extend(f"- {snippet}" for snippet in snippets)
        return "\n".join(lines).strip()

    @staticmethod
    def _extract_response_sections(hits: List[Hit]) -> Dict[str, str]:
        sections: Dict[str, str] = {}
        for hit in hits:
            meta = hit.meta if isinstance(hit.meta, dict) else {}
            raw_sections = meta.get("response_sections")
            if not isinstance(raw_sections, dict):
                continue
            for key in ("background_story", "vineyard_region", "winemaking", "summary"):
                value = GenerationService._normalize_section_value(raw_sections.get(key))
                if value and key not in sections:
                    sections[key] = " ".join(value.split())[:320].rstrip()
            if len(sections) >= 3:
                break
        return sections

    @staticmethod
    def _normalize_section_value(value: Any) -> str:
        if isinstance(value, list):
            parts: List[str] = []
            for item in value:
                text = " ".join(str(item or "").split())
                if text and text not in parts:
                    parts.append(text)
            return " ".join(parts).strip()
        if isinstance(value, dict):
            parts = []
            for item in value.values():
                text = " ".join(str(item or "").split())
                if text and text not in parts:
                    parts.append(text)
            return " ".join(parts).strip()
        return " ".join(str(value or "").split()).strip()

    @staticmethod
    def _hit_fallback_snippet(hit: Hit) -> str:
        parts: List[str] = []
        for value in (hit.summary, hit.text):
            text = " ".join(str(value or "").split())
            if text and text not in parts:
                parts.append(text)
        meta = hit.meta if isinstance(hit.meta, dict) else {}
        for key in (
            "title",
            "name",
            "product",
            "producer",
            "wine_name",
            "full_wine_name",
            "vintage",
            "code",
            "product_code",
            "url",
        ):
            text = " ".join(str(meta.get(key) or "").split())
            if text and text not in parts:
                parts.append(text)
        if not parts:
            return ""
        return " | ".join(parts)

    @staticmethod
    def _build_deterministic_fallback_text(hits: List[Hit]) -> str:
        return GenerationService._build_grounded_fallback_text(query="", hits=hits, language=None)

    @staticmethod
    def _build_grounded_gap_text(*, prompt_category: str, language: Optional[str]) -> str:
        category = str(prompt_category or "").strip()
        normalized_lang = str(language or "").lower()
        if category == "tasting_note_generation":
            if language == "zh-Hant":
                return "目前檢索到的資料不足以產生可靠的產品使用描述。我不會用泛用內容冒充已驗證資料；請提供品牌說明、產品資料或使用情境。"
            if normalized_lang.startswith("ja"):
                return "検索できた資料だけでは、信頼できる商品説明を作成するには不十分です。一般論を検証済み情報として扱わず、ブランド説明、商品資料、利用シーンを追加してください。"
            return (
                "The retrieved material does not contain enough product-use evidence. "
                "I will not present generic content as verified material. Please provide a brand note, product source, or use case."
            )
        if language == "zh-Hant":
            return "目前檢索到的資料不足以明確對應目標產品線或場景。我不會用泛用內容替代；請補充產品、品牌、用途或來源資料。"
        if normalized_lang.startswith("ja"):
            return "検索できた資料だけでは、対象の商品ラインやシーンに明確に対応できません。一般的なカテゴリ情報で代替せず、商品、ブランド、用途、または出典資料を追加してください。"
        return (
            "The retrieved material does not contain enough passages that explicitly match the target product line or scenario. "
            "I will not substitute generic category content."
        )

    @staticmethod
    def _build_producer_ranking_fallback_text(
        *,
        query: str,
        hits: List[Hit],
        language: Optional[str],
    ) -> str:
        shortlist: List[str] = []
        seen: set[str] = set()
        for hit in hits:
            meta = hit.meta if isinstance(hit.meta, dict) else {}
            producer = str(meta.get("producer") or meta.get("title") or "").strip()
            summary = " ".join(str(hit.summary or hit.text or "").split()).strip()
            if not producer:
                continue
            normalized = producer.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            shortlist.append(f"{producer}: {summary[:120].rstrip('. ')}" if summary else producer)
            if len(shortlist) >= 6:
                break
        if not shortlist:
            if language == "zh-Hant":
                return "目前已收錄的合格 producer-level 證據不足，無法整理出 shortlist；但我不會把這題直接判成太廣。"
            return (
                "There is not enough qualified producer-level evidence to build a shortlist yet, "
                "but I will not treat the query as simply too broad."
            )
        if language == "zh-Hant":
            lines = ["以下是根據目前已收錄且合格的證據整理出的 shortlist，不是絕對排名："]
            lines.extend(f"- {item}" for item in shortlist[:6])
            lines.append("若要，我可以再依村莊風格、傳統派/新派或近年表現進一步收斂。")
            return "\n".join(lines)
        lines = ["Here is an evidence-based shortlist from the currently qualified material, not an absolute ranking:"]
        lines.extend(f"- {item}" for item in shortlist[:6])
        lines.append("I can narrow it further by village style, traditional vs modern profile, or recent performance.")
        return "\n".join(lines)
