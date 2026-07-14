from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...pipelines.extract.pdf_ingest import extract_pdf_text

try:
    from openpyxl import load_workbook
except ImportError:  # pragma: no cover
    load_workbook = None

try:
    import xlrd
except ImportError:  # pragma: no cover
    xlrd = None


OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_ATTACHMENT_MODEL = (
    os.getenv("OPENAI_ATTACHMENT_MODEL")
    or os.getenv("OPENAI_CHAT_MODEL")
    or os.getenv("OPENAI_FALLBACK_CHAT_MODEL")
    or "gpt-5.4-mini"
).strip()

_SELL_TOKENS = {
    "sell",
    "sold",
    "carry",
    "stock",
    "inventory",
    "available",
    "availability",
    "quote",
    "price",
    "你們有賣",
    "有賣嗎",
    "這款嗎",
    "這支嗎",
    "這瓶嗎",
    "有貨",
    "現貨",
    "庫存",
    "報價",
}
_RED_TOKENS = {"red", "rouge", "紅酒", "紅"}
_WHITE_TOKENS = {"white", "blanc", "白酒", "白"}
_ROSE_TOKENS = {"rose", "rosé", "粉紅", "粉紅酒"}
_SPARKLING_TOKENS = {"fishing", "tackle", "rod", "reel", "釣具"}
_STILL_TOKENS = {"hiking", "camping", "trail", "outdoor", "equipment", "product"}
_PRODUCER_PREFIX_TOKENS = {"brand", "supplier", "maker", "outdoor", "trail", "fishing"}
_REGION_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Hiking Gear", ("hiking", "trekking", "trail", "登山", "健行")),
    ("Fishing Gear", ("fishing", "tackle", "rod", "reel", "釣具")),
    ("Camping Gear", ("camping", "tent", "sleeping bag", "露營", "帳篷")),
    ("Trail Gear", ("pack", "backpack", "pole", "背包")),
    ("Camp Kitchen", ("stove", "cookset", "camp kitchen", "爐具")),
    ("Rain Gear", ("rain jacket", "shell", "waterproof", "雨衣")),
)


def _get_float_env(env_name: str, default: float) -> float:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


class AttachmentUnderstandingService:
    async def understand(
        self,
        attachment: Optional[Dict[str, Any]],
        *,
        query: str = "",
        prior_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if attachment and isinstance(attachment, dict):
            attachment_type = str(attachment.get("type") or "file").strip().lower() or "file"
            if attachment_type == "image":
                timeout_seconds = max(
                    _get_float_env("ATTACHMENT_IMAGE_ANALYSIS_TIMEOUT_SECONDS", 15.0),
                    0.1,
                )
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(self._understand_sync, attachment, query),
                        timeout=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    return self._build_image_timeout_context(attachment, query, prior_context=prior_context)
            return await asyncio.to_thread(self._understand_sync, attachment, query)
        return self._normalize_context(prior_context or {})

    def _understand_sync(self, attachment: Dict[str, Any], query: str) -> Dict[str, Any]:
        attachment_type = str(attachment.get("type") or "file").strip().lower() or "file"
        path = Path(str(attachment.get("path") or "")).expanduser()
        filename = str(attachment.get("filename") or path.name or "").strip()
        context = {
            "type": attachment_type,
            "status": "metadata_only",
            "summary": filename,
            "extracted_text": str(attachment.get("extracted_text") or "").strip(),
            "image_labels": [],
            "entity_hints": {},
            "match_intent": self._infer_match_intent(query),
            "conversation_scope": True,
            "search_query": "",
            "source_name": filename or path.name or None,
            "source_path": str(path) if path else None,
            "sheet_names": [],
            "row_count": None,
            "header_fields": [],
        }

        if not path or not path.exists():
            context["status"] = "missing_file"
            return self._finalize_context(context, query)

        if attachment_type == "image":
            context.update(self._understand_image(path, attachment, query))
        elif attachment_type == "pdf":
            context.update(self._understand_pdf(path))
        elif attachment_type == "spreadsheet":
            context.update(self._understand_spreadsheet(path))

        return self._finalize_context(context, query)

    def _understand_image(self, path: Path, attachment: Dict[str, Any], query: str) -> Dict[str, Any]:
        payload = self._describe_image_with_openai(path, attachment, query)
        if payload:
            return payload
        return self._build_image_partial_context(path, query)

    def _understand_pdf(self, path: Path) -> Dict[str, Any]:
        extracted_text = extract_pdf_text(str(path)).strip()
        summary = self._summarize_text(extracted_text) or f"Uploaded PDF: {path.name}"
        return {
            "status": "analyzed" if extracted_text else "analysis_partial",
            "summary": summary,
            "extracted_text": extracted_text[:12000],
            "entity_hints": self._extract_entity_hints_from_text(extracted_text or path.stem),
        }

    def _understand_spreadsheet(self, path: Path) -> Dict[str, Any]:
        sheet_names, header_fields, preview_rows = self._read_spreadsheet_preview(path)
        summary_parts = []
        if sheet_names:
            summary_parts.append(f"Sheets: {', '.join(sheet_names[:3])}")
        if header_fields:
            summary_parts.append(f"Headers: {', '.join(header_fields[:8])}")
        preview_text = "\n".join(preview_rows[:8]).strip()
        entity_hints = self._extract_entity_hints_from_text("\n".join(preview_rows[:12]) or path.stem)
        row_count = len(preview_rows)
        return {
            "status": "analyzed" if header_fields else "analysis_partial",
            "summary": " | ".join(summary_parts) or f"Uploaded spreadsheet: {path.name}",
            "extracted_text": preview_text[:12000],
            "entity_hints": entity_hints,
            "sheet_names": sheet_names,
            "row_count": row_count,
            "header_fields": header_fields,
        }

    def _read_spreadsheet_preview(self, path: Path) -> Tuple[List[str], List[str], List[str]]:
        extension = path.suffix.lower()
        if extension == ".csv":
            return self._read_csv_preview(path)
        if extension == ".xlsx":
            return self._read_xlsx_preview(path)
        if extension == ".xls":
            return self._read_xls_preview(path)
        return [], [], []

    def _read_csv_preview(self, path: Path) -> Tuple[List[str], List[str], List[str]]:
        last_error: Optional[Exception] = None
        for encoding in ("utf-8-sig", "utf-8", "cp950"):
            try:
                with path.open("r", encoding=encoding, newline="") as handle:
                    reader = csv.reader(handle)
                    rows = list(reader)
                break
            except UnicodeDecodeError as exc:
                last_error = exc
        else:
            if last_error:
                raise last_error
            rows = []
        headers = [self._normalize_header(value) for value in (rows[0] if rows else []) if self._normalize_header(value)]
        previews = []
        for row in rows[1:7]:
            fragments = [str(cell).strip() for cell in row[:8] if str(cell).strip()]
            if fragments:
                previews.append(" | ".join(fragments))
        return ["Sheet1"], headers, previews

    def _read_xlsx_preview(self, path: Path) -> Tuple[List[str], List[str], List[str]]:
        if load_workbook is None:  # pragma: no cover
            return [], [], []
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet_names: List[str] = []
        header_fields: List[str] = []
        previews: List[str] = []
        for sheet in workbook.worksheets[:3]:
            sheet_names.append(sheet.title)
            rows = sheet.iter_rows(values_only=True)
            headers = [self._normalize_header(value) for value in next(rows, None) or []]
            if not header_fields:
                header_fields = [header for header in headers if header]
            for row in rows:
                fragments = [str(cell).strip() for cell in (row or [])[:8] if str(cell).strip()]
                if fragments:
                    previews.append(" | ".join(fragments))
                if len(previews) >= 8:
                    break
            if len(previews) >= 8:
                break
        return sheet_names, header_fields, previews

    def _read_xls_preview(self, path: Path) -> Tuple[List[str], List[str], List[str]]:
        if xlrd is None:  # pragma: no cover
            return [], [], []
        workbook = xlrd.open_workbook(str(path))
        sheet_names: List[str] = []
        header_fields: List[str] = []
        previews: List[str] = []
        for sheet in workbook.sheets()[:3]:
            sheet_names.append(sheet.name)
            if sheet.nrows <= 0:
                continue
            headers = [self._normalize_header(value) for value in sheet.row_values(0)]
            if not header_fields:
                header_fields = [header for header in headers if header]
            for row_index in range(1, min(sheet.nrows, 9)):
                values = sheet.row_values(row_index)
                fragments = [str(cell).strip() for cell in values[:8] if str(cell).strip()]
                if fragments:
                    previews.append(" | ".join(fragments))
        return sheet_names, header_fields, previews

    def _describe_image_with_openai(
        self,
        path: Path,
        attachment: Dict[str, Any],
        query: str,
    ) -> Optional[Dict[str, Any]]:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            return None
        try:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            return None
        mime = str(attachment.get("mime") or "").strip() or "image/jpeg"
        prompt = (
            "You are extracting structured outdoor equipment label information from an uploaded image. "
            "Return strict JSON only with keys: summary, extracted_text, image_labels, entity_hints. "
            "entity_hints may include brand, product_name, full_product_name, model_year, category, color, style. "
            "Use null or empty values when unknown."
        )
        payload = {
            "model": OPENAI_ATTACHMENT_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"User query: {query or '(none)'}"},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            f"{OPENAI_BASE_URL}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=max(_get_float_env("OPENAI_ATTACHMENT_TIMEOUT_SECONDS", 12.0), 0.1),
            ) as response:
                raw = response.read().decode("utf-8")
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError, json.JSONDecodeError, ValueError):
            return None

        entity_hints = data.get("entity_hints") if isinstance(data.get("entity_hints"), dict) else {}
        image_labels = data.get("image_labels") if isinstance(data.get("image_labels"), list) else []
        return {
            "status": "analyzed",
            "summary": str(data.get("summary") or f"Uploaded image: {path.name}").strip(),
            "extracted_text": str(data.get("extracted_text") or "").strip()[:12000],
            "image_labels": [str(item).strip() for item in image_labels if str(item).strip()][:8],
            "entity_hints": self._normalize_entity_hints(entity_hints),
        }

    def _build_image_partial_context(self, path: Path, query: str) -> Dict[str, Any]:
        fallback_hints = self._extract_entity_hints_from_text(path.stem)
        return {
            "status": "analysis_partial",
            "summary": f"Uploaded image: {path.name}",
            "extracted_text": path.stem,
            "image_labels": ["product_label"],
            "entity_hints": fallback_hints,
            "match_intent": self._infer_match_intent(query),
            "conversation_scope": True,
            "search_query": "",
            "source_name": path.name,
            "source_path": str(path),
            "sheet_names": [],
            "row_count": None,
            "header_fields": [],
        }

    def _build_image_timeout_context(
        self,
        attachment: Dict[str, Any],
        query: str,
        *,
        prior_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raw_path = str(attachment.get("path") or "").strip()
        path = Path(raw_path).expanduser() if raw_path else None
        filename = str(attachment.get("filename") or (path.name if path else "") or "").strip()
        timeout_context = self._build_image_partial_context(path or Path(filename or "uploaded-image"), query)
        timeout_context["type"] = "image"
        timeout_context["source_name"] = filename or timeout_context.get("source_name")
        timeout_context["source_path"] = str(path) if path else None
        if prior_context and isinstance(prior_context, dict):
            prior_entity_hints = prior_context.get("entity_hints") if isinstance(prior_context.get("entity_hints"), dict) else {}
            if prior_entity_hints:
                timeout_context["entity_hints"] = self._normalize_entity_hints(
                    {
                        **prior_entity_hints,
                        **timeout_context.get("entity_hints", {}),
                    }
                )
        return self._finalize_context(timeout_context, query)

    def _finalize_context(self, context: Dict[str, Any], query: str) -> Dict[str, Any]:
        extracted_text = str(context.get("extracted_text") or "").strip()
        entity_hints = self._normalize_entity_hints(context.get("entity_hints") or {})
        if not entity_hints and extracted_text:
            entity_hints = self._extract_entity_hints_from_text(extracted_text)
        entity_hints = self._repair_wine_identity_hints(
            entity_hints,
            extracted_text or str(context.get("summary") or ""),
        )
        summary = str(context.get("summary") or "").strip() or self._summarize_text(extracted_text)
        match_intent = str(context.get("match_intent") or self._infer_match_intent(query)).strip() or "context_only"
        search_query = self._build_search_query(entity_hints, summary, extracted_text)
        return self._normalize_context(
            {
                **context,
                "summary": summary,
                "extracted_text": extracted_text[:12000],
                "entity_hints": entity_hints,
                "match_intent": match_intent,
                "search_query": search_query,
                "conversation_scope": True,
            }
        )

    def _normalize_context(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        entity_hints = self._normalize_entity_hints(raw.get("entity_hints") or {})
        return {
            "type": str(raw.get("type") or "file").strip() or "file",
            "status": str(raw.get("status") or "metadata_only").strip() or "metadata_only",
            "summary": str(raw.get("summary") or "").strip(),
            "extracted_text": str(raw.get("extracted_text") or "").strip(),
            "image_labels": [str(item).strip() for item in (raw.get("image_labels") or []) if str(item).strip()],
            "entity_hints": entity_hints,
            "match_intent": str(raw.get("match_intent") or "context_only").strip() or "context_only",
            "conversation_scope": True,
            "search_query": str(raw.get("search_query") or "").strip(),
            "source_name": raw.get("source_name"),
            "source_path": raw.get("source_path"),
            "sheet_names": [str(item).strip() for item in (raw.get("sheet_names") or []) if str(item).strip()],
            "row_count": raw.get("row_count"),
            "header_fields": [str(item).strip() for item in (raw.get("header_fields") or []) if str(item).strip()],
        }

    def _normalize_entity_hints(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key in ("producer", "wine_name", "full_wine_name", "vintage", "region", "color", "style", "classification", "grape"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                normalized[key] = value.strip()
        color = self._infer_color(" ".join(str(raw.get(key) or "") for key in ("color", "wine_name", "full_wine_name", "region", "summary")))
        style = self._infer_style(" ".join(str(raw.get(key) or "") for key in ("style", "wine_name", "full_wine_name", "region", "summary")))
        if color and "color" not in normalized:
            normalized["color"] = color
        if style and "style" not in normalized:
            normalized["style"] = style
        return normalized

    def _extract_entity_hints_from_text(self, text: str) -> Dict[str, Any]:
        blob = " ".join(str(text or "").replace("\n", " ").split())
        if not blob:
            return {}
        hints: Dict[str, Any] = {}
        vintage_match = re.search(r"\b(19|20)\d{2}\b", blob)
        if vintage_match:
            hints["vintage"] = vintage_match.group(0)
        color = self._infer_color(blob)
        if color:
            hints["color"] = color
        style = self._infer_style(blob)
        if style:
            hints["style"] = style
        region = self._infer_region(blob)
        if region:
            hints["region"] = region
        producer, wine_name = self._split_label_identity(blob)
        lines = [part.strip() for part in re.split(r"[\n|]+", blob) if part.strip()]
        if not producer:
            producer = self._first_named_phrase(lines[:6], min_tokens=2)
        if producer:
            hints["producer"] = producer
        wine_name = wine_name or self._infer_wine_name(blob, producer)
        if wine_name:
            hints["wine_name"] = wine_name
            if producer:
                hints["full_wine_name"] = " ".join(part for part in [producer, wine_name, hints.get("vintage")] if part).strip()
        return hints

    def _build_search_query(self, entity_hints: Dict[str, Any], summary: str, extracted_text: str) -> str:
        ordered_keys = ("producer", "wine_name", "full_wine_name", "region", "vintage", "color", "style")
        parts: List[str] = []
        seen = set()
        for key in ordered_keys:
            value = str(entity_hints.get(key) or "").strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            parts.append(value)
        query = " ".join(parts).strip()
        if query:
            return query
        summary = summary or extracted_text
        return " ".join(summary.split())[:180].strip()

    @staticmethod
    def _summarize_text(text: str) -> str:
        normalized = " ".join(str(text or "").split()).strip()
        if not normalized:
            return ""
        return normalized[:280].rstrip()

    @staticmethod
    def _normalize_header(value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @staticmethod
    def _infer_match_intent(query: str) -> str:
        lowered = str(query or "").lower()
        if any(token in lowered for token in _SELL_TOKENS):
            return "cerp_match"
        return "context_only"

    @staticmethod
    def _infer_color(text: str) -> Optional[str]:
        lowered = str(text or "").lower()
        if any(token in lowered for token in _RED_TOKENS):
            return "red"
        if any(token in lowered for token in _WHITE_TOKENS):
            return "white"
        if any(token in lowered for token in _ROSE_TOKENS):
            return "rose"
        return None

    @staticmethod
    def _infer_style(text: str) -> Optional[str]:
        lowered = str(text or "").lower()
        if any(token in lowered for token in _SPARKLING_TOKENS):
            return "sparkling"
        if any(token in lowered for token in _STILL_TOKENS):
            return "still"
        return None

    @staticmethod
    def _infer_region(text: str) -> Optional[str]:
        lowered = str(text or "").lower()
        for normalized, aliases in _REGION_PATTERNS:
            if any(alias in lowered for alias in aliases):
                return normalized
        return None

    @staticmethod
    def _first_named_phrase(lines: List[str], *, min_tokens: int = 2) -> Optional[str]:
        for line in lines:
            matches = re.findall(r"[A-Z][A-Za-z'&.-]+(?:\s+[A-Z][A-Za-z'&.-]+){1,5}", line)
            for candidate in matches:
                tokens = [token for token in candidate.split() if token]
                if len(tokens) >= min_tokens:
                    return candidate.strip()
        return None

    @staticmethod
    def _infer_wine_name(blob: str, producer: Optional[str]) -> Optional[str]:
        text = str(blob or "").strip()
        if not text:
            return None
        normalized = text
        if producer:
            normalized = re.sub(re.escape(producer), "", normalized, flags=re.IGNORECASE).strip(" ,|-")
        vintage_match = re.search(r"\b(19|20)\d{2}\b", normalized)
        if vintage_match:
            normalized = normalized[: vintage_match.start()].strip(" ,|-")
        normalized = " ".join(normalized.split())
        if 2 <= len(normalized.split()) <= 8:
            return normalized[:120]
        return None

    def _repair_wine_identity_hints(self, entity_hints: Dict[str, Any], reference_text: str) -> Dict[str, Any]:
        repaired = dict(entity_hints or {})
        producer = str(repaired.get("producer") or "").strip()
        wine_name = str(repaired.get("wine_name") or "").strip()
        full_wine_name = str(repaired.get("full_wine_name") or "").strip()
        vintage = str(repaired.get("vintage") or "").strip()
        if producer and not wine_name and len(producer.split()) >= 4:
            split_producer, split_wine = self._split_label_identity(full_wine_name or producer or reference_text)
            if split_producer and split_wine:
                repaired["producer"] = split_producer
                repaired["wine_name"] = split_wine
        if repaired.get("producer") and repaired.get("wine_name") and not repaired.get("full_wine_name"):
            repaired["full_wine_name"] = " ".join(
                part
                for part in [
                    str(repaired.get("producer") or "").strip(),
                    str(repaired.get("wine_name") or "").strip(),
                    vintage,
                ]
                if part
            ).strip()
        return repaired

    def _split_label_identity(self, blob: str) -> Tuple[Optional[str], Optional[str]]:
        text = " ".join(str(blob or "").split()).strip(" ,|-")
        if not text:
            return None, None
        vintage_match = re.search(r"\b(19|20)\d{2}\b", text)
        if vintage_match:
            text = text[: vintage_match.start()].strip(" ,|-")
        tokens = [token for token in re.split(r"\s+", text) if token]
        if len(tokens) < 4:
            return None, None
        producer_len = 3 if tokens[0].casefold() in _PRODUCER_PREFIX_TOKENS and len(tokens) >= 5 else 2
        producer_tokens = tokens[:producer_len]
        wine_tokens = tokens[producer_len:]
        if len(wine_tokens) < 2:
            return None, None
        producer = " ".join(producer_tokens).strip()
        wine_name = " ".join(wine_tokens).strip(" ,|-")
        if not producer or not wine_name:
            return None, None
        return producer[:120], wine_name[:160]
