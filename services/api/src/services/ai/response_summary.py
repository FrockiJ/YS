import asyncio
import json
import re
from typing import Any, Dict, List, Optional

from ...pipelines.llm import openai_client
from .grounding import GroundingService


class ResponseSummaryService:
    """Build concise result-card summary points from the final answer text."""

    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self._timeout_seconds = timeout_seconds

    async def summarize(
        self,
        *,
        answer_text: str,
        language: Optional[str],
        prompt_category: Optional[str] = None,
        fallback_highlights: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        text = str(answer_text or "").strip()
        normalized_language = str(language or "").lower()
        if normalized_language.startswith("zh"):
            lang = "zh-Hant"
        elif normalized_language.startswith("ja"):
            lang = "ja"
        else:
            lang = "en"
        if not text:
            return self._empty_result("empty_answer")

        try:
            points = await asyncio.wait_for(
                self._summarize_with_llm(
                    answer_text=text,
                    language=lang,
                    prompt_category=prompt_category,
                ),
                timeout=self._timeout_seconds,
            )
            cleaned = self._clean_points(points, answer_text=text, language=lang)
            if cleaned:
                return self._result(cleaned, used_llm=True, fallback_reason=None)
            return self._fallback(
                answer_text=text,
                fallback_highlights=fallback_highlights,
                reason="llm_summary_empty_or_invalid",
            )
        except Exception as exc:
            return self._fallback(
                answer_text=text,
                fallback_highlights=fallback_highlights,
                reason=f"{type(exc).__name__}: {exc}",
            )

    async def _summarize_with_llm(
        self,
        *,
        answer_text: str,
        language: str,
        prompt_category: Optional[str],
    ) -> List[str]:
        language_name = (
            "Traditional Chinese"
            if language == "zh-Hant"
            else "natural business Japanese"
            if language == "ja"
            else "English"
        )
        system = (
            "You summarize YS AI final answers for a compact chat result card.\n"
            f"Output language: {language_name}.\n"
            "Return only a JSON array of 2 or 3 short strings.\n"
            "Each string must be a concise key point from the answer.\n"
            "Do not add facts, scores, SKUs, prices, reviewers, rows, pages, stock, or sources that are not in the answer.\n"
            "Do not include markdown headings or citation lists."
        )
        user = (
            f"Prompt category: {prompt_category or 'general'}\n\n"
            "Final answer to summarize:\n"
            f"{answer_text[:6000]}"
        )
        raw = await openai_client.chat_complete(
            system=system,
            user=user,
            temperature=0.1,
        )
        return self._parse_points(raw)

    @staticmethod
    def _parse_points(raw: str) -> List[str]:
        text = str(raw or "").strip()
        if not text:
            return []
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return [str(item) for item in payload]
            if isinstance(payload, dict):
                for key in ("points", "summary_points", "summary"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        return [str(item) for item in value]
        except json.JSONDecodeError:
            pass
        points: List[str] = []
        for line in text.splitlines():
            cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                points.append(cleaned)
        return points

    @classmethod
    def _clean_points(cls, points: List[str], *, answer_text: str, language: str) -> List[str]:
        cleaned: List[str] = []
        for point in points or []:
            normalized = " ".join(str(point or "").split()).strip(" -•*")
            if not normalized:
                continue
            if normalized.lower() in {"summary", "key points", "簡要重點"}:
                continue
            normalized = cls._clip(normalized, max_length=96 if language == "en" else 72)
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
            if len(cleaned) >= 3:
                break
        if len(cleaned) < 2 and len(answer_text) > 280:
            return []
        return cleaned

    @staticmethod
    def _clip(value: str, *, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[:max_length].rstrip() + "..."

    def _fallback(
        self,
        *,
        answer_text: str,
        fallback_highlights: Optional[List[str]],
        reason: str,
    ) -> Dict[str, Any]:
        points = GroundingService._build_result_card_summary_points(
            answer_text=answer_text,
            grounded_highlights=fallback_highlights or [],
        )
        return self._result(points, used_llm=False, fallback_reason=reason)

    @staticmethod
    def _empty_result(reason: str) -> Dict[str, Any]:
        return {
            "points": [],
            "summary": "",
            "metadata": {"mode": "empty", "used_llm": False, "fallback_reason": reason},
        }

    @staticmethod
    def _result(points: List[str], *, used_llm: bool, fallback_reason: Optional[str]) -> Dict[str, Any]:
        safe_points = [str(point) for point in points or [] if str(point or "").strip()][:3]
        return {
            "points": safe_points,
            "summary": "\n".join(safe_points),
            "metadata": {
                "mode": "llm" if used_llm else "fallback",
                "used_llm": used_llm,
                "fallback_reason": fallback_reason,
            },
        }
