import os
import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from ..llm import openai_client
from ...core.chat_history import get_messages_by_conversation, add_message_to_conversation
from ...core.i18n import t, normalize_lang

async def compose_answer(
    query: str,
    hits: List[Dict],
    conversation_id: Optional[str] = None, # Added for conversation history
    analysis_weight: float = 0.0, # General chat defaults to open synthesis; strict routes pass their own grounding mode.
    prompt_template: Optional[str] = None,
    compact: bool = False, # Added for compact mode
    user_id: Optional[int] = None,
    summary: Optional[str] = None,
    alias_terms: Optional[List[str]] = None,
    intent_name: Optional[str] = None,
    prompt_category: Optional[str] = None,
    context_package: Optional[Dict[str, Any]] = None,
    project_context: Optional[Dict[str, Any]] = None,
    history_cutoff: Optional[datetime] = None,
    guardrail_message: Optional[str] = None,
    lang: Optional[str] = None,
    benchmark_trace: bool = False,
) -> Dict:
    """
    Composes an answer using RAG hits and an LLM.
    This version is corrected to use the centralized openai_client and handle conversation history.
    """
    resolved_lang = normalize_lang(lang)
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return {"text": t("compose.missing_openai_key", resolved_lang), "citations": []}

    try:
        analysis_weight = float(analysis_weight)
    except (TypeError, ValueError):
        analysis_weight = 0.0
    analysis_weight = max(0.0, min(1.0, analysis_weight))

    # 將傳入 conversation_id 字串轉成 UUID 物件
    conv_id_uuid = uuid.UUID(conversation_id) if conversation_id else None

    # --- Start of Conversation & Context Logic ---
    history_messages = []
    if conv_id_uuid:
        history_messages = await get_messages_by_conversation(conv_id_uuid)
        if history_cutoff:
            history_messages = _filter_history_after_cutoff(history_messages, history_cutoff)
        history_messages = history_messages[-10:]

    context_sections: List[str] = []
    rag_lines: List[str] = []
    central_context = _format_context_package(context_package)
    if central_context:
        context_sections.append("## Central Context Package\n" + central_context)
    if hits:
        keyword_pool: List[str] = []
        for h in hits:
            meta = _ensure_meta(h)
            summary_text = (h.get("summary") or "").strip()
            raw_text = (h.get("text") or "").strip()
            snippet_parts: List[str] = []
            if summary_text:
                snippet_parts.append(summary_text)
            if raw_text and raw_text not in snippet_parts:
                snippet_parts.append(raw_text)
            snippet = "\n".join(snippet_parts).strip()
            if not snippet:
                continue
            label = meta.get("title") or meta.get("filename") or h.get("filename")
            chunk_idx = h.get("chunk_idx")
            lang_hint = meta.get("language") or meta.get("lang") or meta.get("locale")
            prefix_bits: List[str] = []
            if label is not None and chunk_idx is not None:
                prefix_bits.append(f"{label}#{chunk_idx}")
            elif label:
                prefix_bits.append(str(label))
            if lang_hint:
                prefix_bits.append(str(lang_hint))
            prefix = f"[{' | '.join(prefix_bits)}] " if prefix_bits else ""
            rag_lines.append(f"{prefix}{snippet}".strip())
            for kw in h.get("keywords") or []:
                if kw not in keyword_pool and len(keyword_pool) < 12:
                    keyword_pool.append(kw)
        if rag_lines:
            context_sections.append("## Retrieved Passages\n" + "\n".join(rag_lines))
        if keyword_pool:
            context_sections.append("## Keyword Signals\n" + ", ".join(keyword_pool))
    if summary:
        summary_block = str(summary).strip()
        if summary_block:
            context_sections.append("## Summary From Retrieval\n" + summary_block)
    if alias_terms:
        alias_list = [a for a in alias_terms if a]
        if alias_list:
            alias_block = "\n".join(f"- {a}" for a in alias_list)
            context_sections.append("## Alias Hints\n" + alias_block)
    if intent_name:
        context_sections.append("## Detected Intent\n- " + intent_name)
    profile_instruction = _prompt_profile_instruction(prompt_category, resolved_lang)
    if profile_instruction:
        context_sections.append("## Prompt Profile Contract\n" + profile_instruction)
    if project_context:
        project_label = project_context.get("label") or project_context.get("name") or project_context.get("title")
        project_identifier = project_context.get("id") or project_context.get("project_id")
        descriptor_parts = [part for part in [project_label, project_identifier] if part]
        if descriptor_parts:
            context_sections.append("## Project Context\n- " + " / ".join(descriptor_parts))

    has_retrieved_passages = bool(rag_lines)
    no_rag_general_chat = not has_retrieved_passages and str(prompt_category or "").strip() == "general_chat"
    context_from_docs = "\n\n".join(context_sections).strip() or t("compose.no_context", resolved_lang)
    
    # Choose the prompt template based on the compact flag
    template = prompt_template or (
        t("compose.compact_prompt", resolved_lang)
        if compact
        else t("compose.long_prompt", resolved_lang)
    )
    language_instruction = _language_instruction(resolved_lang)
    system_prompt = (
        language_instruction
        + "\n\n"
        + template.format(context=context_from_docs, query=query, weight=analysis_weight)
    )
    if no_rag_general_chat:
        system_prompt += "\n\n" + t("compose.no_rag_instruction", resolved_lang)

    # The user's current query should be the last message in the history for the LLM.
    # We pass the conversation history separately via the `history` parameter.
    current_user_message = {"role": "user", "content": query}
    full_history = history_messages + [current_user_message]
    trace_payload: Optional[Dict[str, Any]] = None
    if benchmark_trace:
        trace_payload = {
            "trace_kind": "llm_generation",
            "llm_called": True,
            "generation_type": "llm_generation",
            "no_llm_reason": None,
            "system_prompt": system_prompt,
            "context_from_docs": context_from_docs,
            "llm_request_messages": [{"role": "system", "content": system_prompt}, *full_history],
            "history_message_count": len(history_messages),
            "user_message": current_user_message,
        }

    if guardrail_message is not None:
        response_text = guardrail_message
        if trace_payload is not None:
            trace_payload["llm_raw_response"] = response_text
            trace_payload["llm_response_json"] = {"template": "guardrail_message"}
    else:
        llm_temperature = max(0.1, 1.0 - min(0.95, analysis_weight))
        if trace_payload is not None:
            trace_payload["temperature"] = llm_temperature
        response_text = await openai_client.chat_complete(
            system=system_prompt,
            user=query, # `user` is still needed for the fallback logic in openai_client
            history=full_history, # Pass the complete history
            temperature=llm_temperature,
            trace=trace_payload,
        )
        if trace_payload is not None:
            trace_payload["llm_raw_response"] = response_text
    # --- End of Logic ---

    # Save the current exchange to the database using the UUID object
    new_conv_id_uuid = conv_id_uuid
    assistant_message_id = None
    if response_text:
        # If it was a new conversation, add_message_to_conversation will create it and return the new ID.
        project_id = None
        project_label = None
        if isinstance(project_context, dict):
            project_id = project_context.get("id") or project_context.get("project_id")
            project_label = project_context.get("label") or project_context.get("name") or project_context.get("title")
        new_conv_id_uuid = await add_message_to_conversation(
            conv_id_uuid,
            "user",
            query,
            user_id=user_id,
            project_id=project_id,
            project_label=project_label,
        )
        assistant_metadata = (
            {"retrieval_mode": "llm_without_rag", "rag_used": False}
            if no_rag_general_chat
            else None
        )
        _, assistant_message_id = await add_message_to_conversation(
            new_conv_id_uuid,
            "assistant",
            response_text,
            user_id=user_id,
            project_id=project_id,
            project_label=project_label,
            metadata=assistant_metadata,
            return_message_id=True,
        )

    # 返回給前端時，將 UUID 物件轉換回字串
    payload = {
        "text": response_text,
        "citations": [] if no_rag_general_chat else hits,
        "conversation_id": str(new_conv_id_uuid) if new_conv_id_uuid else None,
    }
    if trace_payload is not None or no_rag_general_chat:
        payload["metadata"] = {
            **({"benchmark_trace": trace_payload} if trace_payload is not None else {}),
            **({"retrieval_mode": "llm_without_rag", "rag_used": False} if no_rag_general_chat else {}),
        }
    if assistant_message_id:
        payload["message_id"] = str(assistant_message_id)
    return payload


def _prompt_profile_instruction(prompt_category: Optional[str], lang: Optional[str]) -> str:
    category = str(prompt_category or "").strip()
    if category == "brand_profile":
        if lang == "zh-Hant":
            return (
                "- \u5148\u4ee5 internal approved / internal official \u8b49\u64da\u7d44\u7e54\u7d50\u8ad6\u3002\n"
                "- \u82e5\u78ba\u5be6\u9700\u8981\u5b98\u7db2\u6216\u6700\u65b0\u4e8b\u5be6\uff0c\u518d\u4ee5 external authoritative \u88dc\u5f37\uff0c\u4e0d\u53ef\u53cd\u5ba2\u70ba\u4e3b\u3002\n"
                "- \u82e5\u5167\u90e8\u8b49\u64da\u4e0d\u8db3\uff0c\u8aaa\u660e coverage gap\uff0c\u4e0d\u8981\u628a\u5916\u90e8\u8cc7\u6599\u5f37\u884c\u7576\u6210\u4e3b\u7d50\u8ad6\u3002"
            )
        return (
            "- Build the answer from internal approved and internal official evidence first.\n"
            "- Use external authoritative evidence only as reinforcement when the user asks for official or latest validation.\n"
            "- If internal coverage is thin, state the evidence gap instead of letting external snippets dominate the answer."
        )
    if category == "producer_ranking":
        if lang == "zh-Hant":
            return (
                "- \u8f38\u51fa 3-6 \u5bb6 grounded shortlist\uff0c\u4e0d\u8981\u56de\u6210\u300c\u554f\u984c\u592a\u5ee3\u300d\u3002\n"
                "- \u6bcf\u5bb6\u7528 1 \u884c\u8aaa\u660e\u7406\u7531\uff0c\u4e26\u8a3b\u660e\u9019\u662f\u4f9d\u64da\u76ee\u524d\u5df2\u6536\u9304\u8b49\u64da\u7684 shortlist\uff0c\u4e0d\u662f\u7d55\u5c0d\u6392\u540d\u3002\n"
                "- \u82e5\u8b49\u64da\u8986\u84cb\u4e0d\u8db3\uff0c\u4ecd\u8981\u8aaa\u660e\u9650\u5236\u8207 coverage gap\u3002"
            )
        return (
            "- Produce a grounded shortlist of 3-6 producers instead of refusing a broad producer-ranking query.\n"
            "- Give one concise reason per producer and state that this is an evidence-based shortlist, not an absolute ranking.\n"
            "- If coverage is incomplete, keep the shortlist but explain the limitation."
        )
    if category == "tasting_note_generation":
        if lang == "zh-Hant":
            return (
                "- 優先使用 tasting note、critic note、producer note 或 source notes。\n"
                "- 如果 retrieved passages 沒有品飲筆記，不要補寫 generic tasting note；請明確說明資料缺口。\n"
                "- 每個香氣、口感、尾韻描述都必須能回到引用片段。"
            )
        return (
            "- Prioritize tasting notes, critic notes, producer notes, or source notes.\n"
            "- If retrieved passages do not contain tasting-note evidence, do not invent a generic note; state the data gap.\n"
            "- Every aroma, palate, and finish claim must be grounded in the cited passages."
        )
    if category == "vineyard_lookup":
        if lang == "zh-Hant":
            return (
                "- 只使用明確提到目標 vineyard / climat / lieu-dit / region 的片段。\n"
                "- Vintage overview 或泛用 Burgundy 內容不能取代 vineyard-specific source。\n"
                "- 若片段沒有提到目標地名，請說明沒有足夠對應來源。"
            )
        return (
            "- Use only passages that explicitly mention the target vineyard, climat, lieu-dit, or region.\n"
            "- Vintage overviews or generic Burgundy content must not substitute for vineyard-specific evidence.\n"
            "- If passages do not mention the target place, state that the source coverage is insufficient."
        )
    if category in {"source_validation", "critic_score_lookup"}:
        return (
            "- Fail closed when authoritative citations are missing.\n"
            "- Do not invent scores, sources, page references, URLs, or critic claims."
        )
    if category == "internal_rag_only_validation":
        return (
            "- Answer only from internal RAG, OCR book corpus, internal documents, and authorized licensed review rows supplied in context.\n"
            "- Every factual claim must carry an inline citation marker tied to a retrieved source.\n"
            "- Include a Sources section listing source title/name plus page, row, or source_trace when available.\n"
            "- If a claim is not supported by the supplied internal sources, omit it or place it under Missing / not verified.\n"
            "- Do not use external web knowledge, model memory, or uncited assumptions."
        )
    if category == "exact_review_lookup":
        return (
            "- Use licensed review rows, RAG passages, and authoritative external evidence as the verified layer.\n"
            "- If the exact requested critic/source row is missing, still provide a useful partial answer from authorized alternatives.\n"
            "- Clearly separate Verified facts, Missing / not verified, and Next data needed.\n"
            "- Never invent an exact score, reviewer, tasting note, issue/date, row, page, URL, or drinking window for a missing source."
        )
    if category == "multi_review_compare":
        return (
            "- Build a detailed critic comparison from the retrieved licensed review rows and source traces.\n"
            "- Use these sections: Critic Score & Profile Overview, Source-by-source notes, Where reviewers agree, Where reviewers differ, YS AI professional read, Missing / not verified, Sources.\n"
            "- Compare only exact wine/vintage evidence; do not substitute adjacent vintages or other producers.\n"
            "- Professional interpretation is allowed only after the verified source-by-source facts are shown."
        )
    if category == "source_hierarchy_conflict":
        return (
            "- Produce an analytical answer, not a product list.\n"
            "- Use these sections: Answer, Controlling source by fact type, Example, Evidence comparison, Missing / not verified, Sources.\n"
            "- Current SKU, stock, price, and sellable product-name facts are controlled by CERP/current ERP rows.\n"
            "- Producer-owned current facts are controlled by newer official producer material when it is present in evidence.\n"
            "- Older books and RAG passages may support historical or background context, but must not override current operational product facts.\n"
            "- If CERP rows are present, use them as example evidence while still explaining the source hierarchy decision.\n"
            "- If producer website evidence is missing, state that gap instead of pretending a website comparison was performed."
        )
    if category == "quote_recommendation":
        return (
            "- Recommendations must stay within official, CERP, or portfolio-backed inventory evidence.\n"
            "- Do not use unverified external material for sellable quote decisions."
        )
    return ""


def _language_instruction(lang: Optional[str]) -> str:
    if lang == "ja":
        return (
            "Answer in the same language as the user's latest message.\n"
            "The required output language for this turn is natural business Japanese."
        )
    if lang == "zh-Hant":
        return (
            "Answer in the same language as the user's latest message.\n"
            "The required output language for this turn is Traditional Chinese. Do not use Simplified Chinese."
        )
    return (
        "Answer in the same language as the user's latest message.\n"
        "The required output language for this turn is English."
    )


def _format_context_package(context_package: Optional[Dict[str, Any]]) -> str:
    if not isinstance(context_package, dict):
        return ""
    text = str(context_package.get("text") or "").strip()
    if text:
        return text
    sections = context_package.get("sections")
    if not isinstance(sections, list):
        return ""
    lines = [str(item).strip() for item in sections if str(item or "").strip()]
    return "\n".join(lines).strip()

def _filter_history_after_cutoff(history: List[Dict[str, Any]], cutoff: datetime) -> List[Dict[str, Any]]:
    normalized_cutoff = _normalize_datetime(cutoff)
    if normalized_cutoff is None:
        return history
    filtered = []
    for msg in history:
        created_at = msg.get("created_at")
        if not created_at:
            filtered.append(msg)
            continue
        parsed = _parse_iso_datetime(created_at)
        if not parsed or parsed >= normalized_cutoff:
            filtered.append(msg)
    return filtered


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    snippet = value.strip()
    if snippet.endswith("Z"):
        snippet = snippet[:-1] + "+00:00"
    try:
        return _normalize_datetime(datetime.fromisoformat(snippet))
    except ValueError:
        return None


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    if value.tzinfo:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _ensure_meta(hit: Dict[str, Any]) -> Dict[str, Any]:
    meta = hit.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    if not isinstance(meta, dict):
        meta = {}
    hit["meta"] = meta
    return meta
