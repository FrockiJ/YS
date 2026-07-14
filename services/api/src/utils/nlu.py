import asyncio
import json
import os
import re
from typing import Any, Dict, Optional

from ..pipelines.llm import openai_client

_DEFAULT_TIMEOUT_S = float(os.getenv("OPENAI_NLU_TIMEOUT", "8"))


def _coerce_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return str(value).strip() or None


def _parse_json_payload(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_payload(payload: Dict[str, Any], fallback_text: str) -> Dict[str, Optional[str]]:
    producer = _coerce_text(payload.get("producer"))
    wine_name = _coerce_text(payload.get("wine_name"))
    region = _coerce_text(payload.get("region"))
    vintage = _coerce_text(payload.get("vintage"))
    color = _coerce_text(payload.get("color"))
    style = _coerce_text(payload.get("style"))
    keywords = _coerce_text(payload.get("keywords"))
    if not keywords:
        pieces = [producer, wine_name, region, vintage, color, style]
        keywords = " ".join([p for p in pieces if p])
    return {
        "producer": producer,
        "wine_name": wine_name,
        "region": region,
        "vintage": vintage,
        "color": color,
        "style": style,
        "keywords": keywords or fallback_text.strip(),
    }


async def extract_search_entities(user_input: str) -> Dict[str, Optional[str]]:
    """
    Extract and normalize search entities for quote / CERP lookup via LLM.
    Returns a dict with keys: producer, wine_name, region, vintage, color, style, keywords.
    """
    if not user_input or not user_input.strip():
        return {
            "producer": None,
            "wine_name": None,
            "region": None,
            "vintage": None,
            "color": None,
            "style": None,
            "keywords": "",
        }

    system_prompt = (
        "You are an entity extraction engine for wine search.\n"
        "Return ONLY valid JSON with keys: producer, wine_name, region, vintage, color, style, keywords.\n"
        "Rules:\n"
        "- If a field is unknown, use null.\n"
        "- Normalize producer names to canonical forms when known (e.g., Lafarge Vial -> Lafarge-Vial).\n"
        "- Normalize color to red, white, rose, or orange when known.\n"
        "- Normalize style to sparkling or still when known.\n"
        "- keywords should be a concise search string using normalized fields.\n"
        "No extra text."
    )
    user_prompt = f"Input: {user_input}"

    try:
        response = await asyncio.wait_for(
            openai_client.chat_complete(system_prompt, user_prompt, temperature=0),
            timeout=_DEFAULT_TIMEOUT_S,
        )
    except Exception:
        return {
            "producer": None,
            "wine_name": None,
            "region": None,
            "vintage": None,
            "color": None,
            "style": None,
            "keywords": user_input.strip(),
        }

    payload = _parse_json_payload(response or "")
    if not payload:
        return {
            "producer": None,
            "wine_name": None,
            "region": None,
            "vintage": None,
            "color": None,
            "style": None,
            "keywords": user_input.strip(),
        }
    return _normalize_payload(payload, user_input)
