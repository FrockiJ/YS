from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict

_QUESTION_RUN_RE = re.compile(r"\?{3,}")
_WORDLIKE_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff\u3400-\u4dbf]+")


def assess_text_quality(text: str, *, meta: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized = str(text or "")
    total = max(len(normalized), 1)
    suspicious = 0
    readable = 0
    for char in normalized:
        codepoint = ord(char)
        category = unicodedata.category(char)
        if (
            char == "\ufffd"
            or category in {"Co", "Cs", "Cn"}
            or 0x80 <= codepoint <= 0x9F
        ):
            suspicious += 1
        if char.isalnum() or _is_cjk(char):
            readable += 1

    question_runs = len(_QUESTION_RUN_RE.findall(normalized))
    wordlike = len(_WORDLIKE_RE.findall(normalized))
    suspicious_ratio = suspicious / total
    readable_ratio = readable / total

    encoding_quality = round(max(0.0, 1.0 - min(1.0, suspicious_ratio * 3.0 + question_runs * 0.06)), 4)
    content_quality = round(
        max(
            0.0,
            min(
                1.0,
                readable_ratio
                - question_runs * 0.04
                - (0.15 if wordlike < 8 and total > 120 else 0.0),
            ),
        ),
        4,
    )
    is_garbled = bool(
        suspicious_ratio >= 0.015
        or question_runs >= 2
        or (total > 160 and readable_ratio < 0.34)
        or (total > 80 and wordlike < 6)
    )

    if meta and _looks_like_internal_authoritative_source(meta):
        # Do not aggressively downgrade internal sources unless the text is clearly broken.
        is_garbled = bool(is_garbled and suspicious_ratio >= 0.03)

    return {
        "content_quality": content_quality,
        "encoding_quality": encoding_quality,
        "is_garbled": is_garbled,
        "quality_flags": _quality_flags(
            suspicious_ratio=suspicious_ratio,
            question_runs=question_runs,
            readable_ratio=readable_ratio,
            wordlike=wordlike,
            is_garbled=is_garbled,
        ),
    }


def merge_quality_metadata(meta: Dict[str, Any] | None, text: str) -> Dict[str, Any]:
    merged = dict(meta or {})
    quality = assess_text_quality(text, meta=merged)
    merged.update(quality)
    return merged


def _quality_flags(
    *,
    suspicious_ratio: float,
    question_runs: int,
    readable_ratio: float,
    wordlike: int,
    is_garbled: bool,
) -> list[str]:
    flags: list[str] = []
    if suspicious_ratio >= 0.015:
        flags.append("suspicious_unicode")
    if question_runs >= 2:
        flags.append("question_run_noise")
    if readable_ratio < 0.34:
        flags.append("low_readable_ratio")
    if wordlike < 6:
        flags.append("low_wordlike_count")
    if is_garbled:
        flags.append("garbled")
    return flags


def _is_cjk(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x2A700 <= codepoint <= 0x2B73F
        or 0x2B740 <= codepoint <= 0x2B81F
        or 0x2B820 <= codepoint <= 0x2CEAF
    )


def _looks_like_internal_authoritative_source(meta: Dict[str, Any]) -> bool:
    search_blob = " ".join(
        str(meta.get(key) or "")
        for key in ("source_tier", "source", "url", "source_url", "domain", "filename")
    ).lower()
    return any(token in search_blob for token in ("internal_primary", "internal_official", "cerp", "ys.local"))
