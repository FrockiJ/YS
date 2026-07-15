from __future__ import annotations

import asyncio
import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from ..core import config, db
from ..pipelines.extract.chunker import guided_pdf_chunks
from ..pipelines.extract.enrich import enrich_chunk
from ..pipelines.extract.official_site import (
    OfficialSiteSeed,
    build_profile_chunks,
    build_profile_from_product_page,
    normalize_seed,
    parse_discovery_html,
)
from ..pipelines.extract.ingest_log import compute_file_signature, log_ingest_result
from ..pipelines.extract.pdf_ingest import iter_pages_text
from ..pipelines.extract.quality import merge_quality_metadata
from ..pipelines.extract.spreadsheet_ingest import iter_spreadsheet_chunks
from ..pipelines.nlp.embedder import embed_texts
from ..pipelines.nlp.ner_alias import extract_entities_and_alias
from ..pipelines.rag.indexer import (
    clear_document_payload,
    delete_documents_by_ids,
    insert_alias,
    insert_chunks,
    insert_entities,
    upsert_document,
)
from ..utils.cerp_export_lookup import list_export_brands

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 32
_PDF_CHUNK_SIZE = 1000
_PROGRESS_UPDATE_INTERVAL = 50
def normalize_official_brand_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(part for part in "".join(ch if ch.isalnum() else " " for ch in text).split() if part)


def official_site_delay_seconds() -> float:
    per_minute = max(int(config.OFFICIAL_RATE_LIMIT_PER_MINUTE or 1), 1)
    return max(60.0 / per_minute, 0.0)


class ExtractRequest(BaseModel):
    source_scope: str = "knowledge"
    file_types: List[str] = Field(default_factory=list)
    rebuild_mode: str = "incremental"
    input_roots: List[str] = Field(default_factory=list)
    execution_mode: str = "sync"
    requested_by: Optional[str] = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def data_root() -> Path:
    return Path(config.DATA_DIR).resolve()


def default_books_root() -> Path:
    current_data_dir = data_root()
    preferred = current_data_dir / "book"
    return preferred if preferred.exists() else current_data_dir


def default_spreadsheet_root() -> Optional[Path]:
    raw = (config.EXTRACT_SPREADSHEET_DIR or "").strip()
    if not raw:
        return None
    return Path(raw).resolve()


def normalize_file_types(file_types: Sequence[str]) -> List[str]:
    allowed = {"pdf", "xlsx", "xls", "csv"}
    normalized: List[str] = []
    for item in file_types:
        value = str(item or "").strip().lower().lstrip(".")
        if value in allowed and value not in normalized:
            normalized.append(value)
    return normalized


def normalize_scope(scope: str) -> str:
    value = str(scope or "").strip().lower()
    return value if value in {"all", "knowledge", "books", "spreadsheets", "official_site"} else "knowledge"


def normalize_rebuild_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"incremental", "rechunk", "full"} else "incremental"


def normalize_execution_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"sync", "async"} else "sync"


def normalize_extract_request(payload: ExtractRequest, *, user: Optional[dict] = None) -> ExtractRequest:
    return ExtractRequest(
        source_scope=normalize_scope(payload.source_scope),
        file_types=normalize_file_types(payload.file_types),
        rebuild_mode=normalize_rebuild_mode(payload.rebuild_mode),
        input_roots=payload.input_roots,
        execution_mode=normalize_execution_mode(payload.execution_mode),
        requested_by=payload.requested_by or ((user or {}).get("username") if isinstance(user, dict) else None),
    )


def request_uses_virtual_sources(request: ExtractRequest) -> bool:
    return normalize_scope(request.source_scope) == "official_site"


def default_official_collection_roots() -> List[str]:
    raw = str(config.OFFICIAL_COLLECTION_ROOTS or "").strip()
    if not raw:
        return []
    roots: List[str] = []
    for item in raw.split(","):
        text = str(item or "").strip()
        if text and text not in roots:
            roots.append(text)
    return roots


def resolve_input_roots(request: ExtractRequest) -> List[Path]:
    roots: List[Path] = []
    for item in request.input_roots:
        raw = str(item or "").strip()
        if not raw:
            continue
        roots.append(Path(raw).resolve())
    if roots:
        return roots

    scope = normalize_scope(request.source_scope)
    if scope == "books":
        return [default_books_root()]
    if scope == "spreadsheets":
        spreadsheet_root = default_spreadsheet_root()
        return [spreadsheet_root] if spreadsheet_root else []
    if scope == "official_site":
        return []
    if scope == "knowledge":
        roots = [default_books_root()]
        spreadsheet_root = default_spreadsheet_root()
        if spreadsheet_root:
            roots.append(spreadsheet_root)
        return roots
    roots = [data_root()]
    spreadsheet_root = default_spreadsheet_root()
    if spreadsheet_root:
        roots.append(spreadsheet_root)
    return roots


async def collect_existing_official_handles(conn) -> List[str]:
    rows = await conn.fetch(
        """
        SELECT product_handle
        FROM official_product_profiles
        WHERE COALESCE(is_active, TRUE) = TRUE
        ORDER BY updated_at DESC
        LIMIT 500
        """
    )
    handles: List[str] = []
    for row in rows:
        handle = str(row["product_handle"] or "").strip()
        if handle and handle not in handles:
            handles.append(handle)
    return handles


async def collect_official_site_seeds(request: ExtractRequest) -> List[OfficialSiteSeed]:
    base_url = str(config.OFFICIAL_BASE_URL or "").rstrip("/")
    raw_inputs = [str(item or "").strip() for item in request.input_roots if str(item or "").strip()]
    seeds: List[str] = []
    if raw_inputs:
        seeds.extend(raw_inputs)
    else:
        seeds.extend(default_official_collection_roots())
        existing_handles = []
        try:
            conn = await db.get_conn()
            try:
                existing_handles = await collect_existing_official_handles(conn)
            finally:
                await conn.close()
        except Exception:
            logger.exception("Failed to load existing official product handles")
        for handle in existing_handles[:200]:
            seeds.append(f"/products/{handle}")
        for brand in list_export_brands()[:200]:
            seeds.append(brand)

    normalized: List[OfficialSiteSeed] = []
    seen: set[str] = set()
    for item in seeds:
        seed = normalize_seed(base_url, item)
        key = f"{seed.seed_type}:{seed.value}".lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(seed)
    return normalized


async def count_extract_work_items(request: ExtractRequest) -> int:
    if request_uses_virtual_sources(request):
        return len(await collect_official_site_seeds(request))
    return len(collect_source_files(request))


def iter_files_under(root: Path, file_types: Sequence[str]) -> Iterable[Path]:
    for ext in file_types:
        pattern = f"**/*.{ext}"
        yield from root.glob(pattern)


def collect_source_files(request: ExtractRequest) -> List[Path]:
    scope = normalize_scope(request.source_scope)
    file_types = normalize_file_types(request.file_types)
    if not file_types:
        if scope == "books":
            file_types = ["pdf"]
        elif scope == "spreadsheets":
            file_types = ["xlsx", "xls", "csv"]
        else:
            file_types = ["pdf", "xlsx", "xls", "csv"]

    files: List[Path] = []
    seen: set[str] = set()
    for root in resolve_input_roots(request):
        if not root or not root.exists():
            continue
        if root.is_file():
            key = str(root.resolve()).lower()
            if key not in seen:
                seen.add(key)
                files.append(root.resolve())
            continue
        for path in iter_files_under(root, file_types):
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            files.append(path.resolve())
    return sorted(files)


def classify_source_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".xlsx", ".xls", ".csv"}:
        return "spreadsheet"
    return "file"


def document_meta_for(path: Path) -> Dict[str, Any]:
    kind = classify_source_kind(path)
    return {
        "filetype": kind,
        "source_group": "knowledge",
        "source_kind": kind,
        "source_path": str(path.resolve()),
        "filename": path.name,
    }


def official_document_filename(handle: str) -> str:
    return f"official_site:{handle}"


def official_document_meta(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "filetype": "web",
        "source_group": "official_site",
        "source_kind": "product_json",
        "source_path": profile.get("official_url"),
        "official_url": profile.get("official_url"),
        "product_handle": profile.get("product_handle"),
        "brand": profile.get("brand"),
        "availability": profile.get("availability"),
        "source_tier": "internal_official",
        "filename": official_document_filename(str(profile.get("product_handle") or "")),
    }


def merge_fields_into_meta(base_meta: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base_meta)
    filtered_fields = _filter_extracted_fields_for_contract(base_meta, fields or {})
    for key, value in filtered_fields.items():
        if value in (None, "", [], {}):
            continue
        existing = merged.get(key)
        if existing in (None, "", [], {}):
            merged[key] = value
    return _normalize_chunk_meta_contract(merged)


def build_chunk_record(
    *,
    chunk_idx: int,
    text: str,
    base_meta: Dict[str, Any],
    alias_source: str,
) -> Dict[str, Any]:
    entities, aliases, fields = extract_entities_and_alias(text)
    summary, keywords, kag = enrich_chunk(text, fields)
    meta = merge_fields_into_meta(base_meta, fields)
    meta = merge_quality_metadata(meta, text)
    return {
        "chunk_idx": chunk_idx,
        "text": text,
        "meta": meta,
        "summary": summary,
        "keywords": keywords,
        "kg": kag,
        "aliases": [
            {
                "canonical": alias.get("canonical"),
                "variant": alias.get("variant"),
                "type": alias.get("type"),
                "lang": alias.get("lang", "auto"),
                "source": alias_source,
                "confidence": alias.get("confidence", 0.8),
            }
            for alias in (aliases or [])
            if alias.get("canonical") and alias.get("variant")
        ],
        "entities": entities or [],
    }


def _normalize_contract_token(value: Any) -> str:
    text = str(value or "").strip().casefold()
    return " ".join(text.replace("-", " ").split())


def _filter_extracted_fields_for_contract(base_meta: Dict[str, Any], fields: Dict[str, Any]) -> Dict[str, Any]:
    return dict(fields)


def _normalize_chunk_meta_contract(meta: Dict[str, Any]) -> Dict[str, Any]:
    return dict(meta)


def dedupe_alias_rows(chunk_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    alias_map: Dict[tuple, Dict[str, Any]] = {}
    for chunk in chunk_records:
        for alias in chunk.get("aliases") or []:
            key = (alias.get("canonical"), alias.get("variant"), alias.get("type"))
            if key in alias_map:
                continue
            alias_map[key] = alias
    return list(alias_map.values())


async def batch_embed_async(
    chunk_records: List[Dict[str, Any]],
    *,
    on_batch_done: Any = None,
) -> None:
    total = len(chunk_records)
    if total == 0:
        if on_batch_done:
            await on_batch_done(0, 0)
        return
    for index in range(0, total, _EMBED_BATCH_SIZE):
        batch = chunk_records[index:index + _EMBED_BATCH_SIZE]
        vectors = await asyncio.to_thread(embed_texts, [item["text"] for item in batch])
        for offset, vector in enumerate(vectors):
            batch[offset]["embedding"] = vector
        if on_batch_done:
            await on_batch_done(min(index + len(batch), total), total)


def build_pdf_chunk_records_sync(file_path: Path) -> List[Dict[str, Any]]:
    source_path = str(file_path.resolve())
    chunk_records: List[Dict[str, Any]] = []
    chunk_idx = 0
    for page_no, page_text in iter_pages_text(source_path):
        for chunk_text in guided_pdf_chunks(page_text or "", max_len=_PDF_CHUNK_SIZE):
            base_meta = {
                "filename": file_path.name,
                "page": page_no,
                "source_group": "knowledge",
                "source_kind": "pdf",
                "source_path": source_path,
            }
            chunk_records.append(
                build_chunk_record(
                    chunk_idx=chunk_idx,
                    text=chunk_text,
                    base_meta=base_meta,
                    alias_source=source_path,
                )
            )
            chunk_idx += 1
    return chunk_records


def build_spreadsheet_records_sync(file_path: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    source_path = str(file_path.resolve())
    payloads = list(iter_spreadsheet_chunks(file_path))
    if not payloads:
        return [], []

    chunk_records: List[Dict[str, Any]] = []
    for chunk_idx, payload in enumerate(payloads):
        chunk_meta = dict(payload.get("meta") or {})
        base_meta = {
            "filename": file_path.name,
            "source_group": "knowledge",
            "source_kind": "spreadsheet",
            "source_path": source_path,
        }
        base_meta.update(chunk_meta)
        chunk_records.append(
            build_chunk_record(
                chunk_idx=chunk_idx,
                text=str(payload.get("chunk_text") or ""),
                base_meta=base_meta,
                alias_source=source_path,
            )
        )
    return [], chunk_records


async def upsert_official_product_profile(conn, profile: Dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO official_product_profiles (
            product_handle, product_title, brand, product_type, official_url, product_json_hash,
            availability, price_min, price_max, images_json, variants_json, tags_json,
            description_html, description_text, search_terms_json, source_payload_json,
            source_tier, last_seen_at, is_active
        )
        VALUES (
            $1, $2, $3, $4, $5, $6,
            $7, $8, $9, $10::jsonb, $11::jsonb, $12::jsonb,
            $13, $14, $15::jsonb, $16::jsonb,
            $17, NOW(), $18
        )
        ON CONFLICT (product_handle) DO UPDATE
        SET
            product_title = EXCLUDED.product_title,
            brand = EXCLUDED.brand,
            product_type = EXCLUDED.product_type,
            official_url = EXCLUDED.official_url,
            product_json_hash = EXCLUDED.product_json_hash,
            availability = EXCLUDED.availability,
            price_min = EXCLUDED.price_min,
            price_max = EXCLUDED.price_max,
            images_json = EXCLUDED.images_json,
            variants_json = EXCLUDED.variants_json,
            tags_json = EXCLUDED.tags_json,
            description_html = EXCLUDED.description_html,
            description_text = EXCLUDED.description_text,
            search_terms_json = EXCLUDED.search_terms_json,
            source_payload_json = EXCLUDED.source_payload_json,
            source_tier = EXCLUDED.source_tier,
            last_seen_at = NOW(),
            is_active = EXCLUDED.is_active,
            updated_at = NOW()
        """,
        profile.get("product_handle"),
        profile.get("product_title"),
        profile.get("brand"),
        profile.get("product_type"),
        profile.get("official_url"),
        profile.get("product_json_hash"),
        profile.get("availability"),
        profile.get("price_min"),
        profile.get("price_max"),
        json.dumps(profile.get("images_json") or [], ensure_ascii=False),
        json.dumps(profile.get("variants_json") or [], ensure_ascii=False),
        json.dumps(profile.get("tags_json") or [], ensure_ascii=False),
        profile.get("description_html"),
        profile.get("description_text"),
        json.dumps(profile.get("search_terms_json") or [], ensure_ascii=False),
        json.dumps(profile.get("source_payload_json") or {}, ensure_ascii=False),
        profile.get("source_tier") or "internal_official",
        bool(profile.get("is_active", True)),
    )


async def sync_official_brand_domain(conn, profile: Dict[str, Any]) -> None:
    brand = str(profile.get("brand") or "").strip()
    if not brand:
        return
    normalized = normalize_official_brand_name(brand)
    if not normalized:
        return
    domain = urlparse(str(profile.get("official_url") or "")).netloc.lower().lstrip("www.")
    if not domain:
        domain = "ys.local"
    exists = await conn.fetchval(
        """
        SELECT EXISTS(
            SELECT 1
            FROM brand_source_domains
            WHERE brand_name_normalized = $1
              AND domain = $2
              AND source_origin = 'ys_site'
        )
        """,
        normalized,
        domain,
    )
    if exists:
        return
    await conn.execute(
        """
        INSERT INTO brand_source_domains (
            brand_name_raw, brand_name_normalized, source_kind, domain, source_tier,
            source_origin, verification_status, region_scope, notes, created_at, updated_at
        )
        VALUES ($1, $2, 'official', $3, 'internal_official', 'ys_site', 'verified', NULL, 'synced from official product profile', NOW(), NOW())
        """,
        brand,
        normalized,
        domain,
    )


async def delete_official_product_profiles(
    conn,
    *,
    handles: Sequence[str] | None = None,
    official_urls: Sequence[str] | None = None,
) -> None:
    normalized_handles = [str(item) for item in (handles or []) if str(item or "").strip()]
    normalized_urls = [str(item) for item in (official_urls or []) if str(item or "").strip()]
    if normalized_handles and normalized_urls:
        await conn.execute(
            "DELETE FROM official_product_profiles WHERE product_handle = ANY($1::text[]) OR official_url = ANY($2::text[])",
            normalized_handles,
            normalized_urls,
        )
        return
    if normalized_handles:
        await conn.execute("DELETE FROM official_product_profiles WHERE product_handle = ANY($1::text[])", normalized_handles)
        return
    if normalized_urls:
        await conn.execute("DELETE FROM official_product_profiles WHERE official_url = ANY($1::text[])", normalized_urls)


async def spreadsheet_has_chunks(conn, *, document_id: int, source_file: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM chunks
                WHERE document_id = $1
            )
            """,
            document_id,
        )
    )


async def find_existing_documents(conn, files: Sequence[Path]) -> List[Dict[str, Any]]:
    filenames = [path.name for path in files]
    source_paths = [str(path.resolve()) for path in files]
    if not filenames and not source_paths:
        return []
    rows = await conn.fetch(
        """
        SELECT id, filename, meta
        FROM documents
        WHERE filename = ANY($1::text[])
           OR COALESCE(meta->>'source_path', '') = ANY($2::text[])
        """,
        filenames or [""],
        source_paths or [""],
    )
    return [dict(row) for row in rows]


async def find_existing_official_documents(conn, handles: Sequence[str]) -> List[Dict[str, Any]]:
    normalized = [official_document_filename(str(handle)) for handle in handles if str(handle or "").strip()]
    if not normalized:
        return []
    rows = await conn.fetch(
        """
        SELECT id, filename, meta
        FROM documents
        WHERE filename = ANY($1::text[])
           OR COALESCE(meta->>'product_handle', '') = ANY($2::text[])
        """,
        normalized,
        [str(handle) for handle in handles],
    )
    return [dict(row) for row in rows]


async def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


async def backup_snapshot(conn, *, files: Sequence[Path], docs: Sequence[Dict[str, Any]]) -> Optional[str]:
    if not docs:
        return None
    upload_root = Path(config.UPLOAD_STORAGE_PATH or "py/S3")
    if not upload_root.is_absolute():
        upload_root = (Path.cwd() / upload_root).resolve()
    snapshot_dir = upload_root / "knowledge_backups" / utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    doc_ids = [int(doc["id"]) for doc in docs]
    filenames = [path.name for path in files]
    source_paths = [str(path.resolve()) for path in files]

    chunk_rows = await conn.fetch("SELECT * FROM chunks WHERE document_id = ANY($1::int[])", doc_ids)
    chunk_ids = [int(row["id"]) for row in chunk_rows]
    entity_rows = await conn.fetch("SELECT * FROM entities WHERE chunk_id = ANY($1::int[])", chunk_ids or [0])
    alias_rows = await conn.fetch(
        "SELECT * FROM alias WHERE source = ANY($1::text[])",
        list(dict.fromkeys(filenames + source_paths)) or [""],
    )
    ingest_rows = await conn.fetch(
        "SELECT * FROM ingest_log WHERE filename = ANY($1::text[])",
        filenames or [""],
    )
    manifest = {
        "created_at": utcnow().isoformat(),
        "files": source_paths,
        "document_count": len(docs),
        "chunk_count": len(chunk_rows),
        "entity_count": len(entity_rows),
        "alias_count": len(alias_rows),
        "ingest_log_count": len(ingest_rows),
    }
    (snapshot_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    await write_jsonl(snapshot_dir / "documents.jsonl", docs)
    await write_jsonl(snapshot_dir / "chunks.jsonl", [dict(row) for row in chunk_rows])
    await write_jsonl(snapshot_dir / "entities.jsonl", [dict(row) for row in entity_rows])
    await write_jsonl(snapshot_dir / "aliases.jsonl", [dict(row) for row in alias_rows])
    await write_jsonl(snapshot_dir / "ingest_log.jsonl", [dict(row) for row in ingest_rows])
    return str(snapshot_dir)


async def backup_official_snapshot(conn, *, handles: Sequence[str], docs: Sequence[Dict[str, Any]]) -> Optional[str]:
    if not docs and not handles:
        return None
    upload_root = Path(config.UPLOAD_STORAGE_PATH or "py/S3")
    if not upload_root.is_absolute():
        upload_root = (Path.cwd() / upload_root).resolve()
    snapshot_dir = upload_root / "official_site_backups" / utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    doc_ids = [int(doc["id"]) for doc in docs]
    handle_list = [str(handle) for handle in handles if str(handle or "").strip()]
    chunk_rows = await conn.fetch("SELECT * FROM chunks WHERE document_id = ANY($1::int[])", doc_ids or [0])
    chunk_ids = [int(row["id"]) for row in chunk_rows]
    entity_rows = await conn.fetch("SELECT * FROM entities WHERE chunk_id = ANY($1::int[])", chunk_ids or [0])
    alias_rows = await conn.fetch(
        "SELECT * FROM alias WHERE source = ANY($1::text[])",
        [str((doc.get('meta') or {}).get('source_path') or '') for doc in docs if str((doc.get('meta') or {}).get('source_path') or '').strip()] or [""],
    )
    profile_rows = await conn.fetch(
        "SELECT * FROM official_product_profiles WHERE product_handle = ANY($1::text[])",
        handle_list or [""],
    )
    manifest = {
        "created_at": utcnow().isoformat(),
        "handles": handle_list,
        "document_count": len(docs),
        "chunk_count": len(chunk_rows),
        "entity_count": len(entity_rows),
        "alias_count": len(alias_rows),
        "profile_count": len(profile_rows),
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    await write_jsonl(snapshot_dir / "documents.jsonl", docs)
    await write_jsonl(snapshot_dir / "chunks.jsonl", [dict(row) for row in chunk_rows])
    await write_jsonl(snapshot_dir / "entities.jsonl", [dict(row) for row in entity_rows])
    await write_jsonl(snapshot_dir / "aliases.jsonl", [dict(row) for row in alias_rows])
    await write_jsonl(snapshot_dir / "official_product_profiles.jsonl", [dict(row) for row in profile_rows])
    return str(snapshot_dir)


async def delete_existing_documents(conn, *, files: Sequence[Path], docs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not docs:
        return {"documents": 0, "chunks": 0, "entities": 0}
    doc_ids = [int(doc["id"]) for doc in docs]
    filenames = [path.name for path in files]
    return await delete_documents_by_ids(conn, doc_ids, filenames=filenames)


async def delete_existing_official_documents(conn, *, handles: Sequence[str], docs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not docs and not handles:
        return {"documents": 0, "chunks": 0, "entities": 0}
    doc_ids = [int(doc["id"]) for doc in docs]
    source_paths = [str((doc.get("meta") or {}).get("source_path") or "") for doc in docs]
    await delete_official_product_profiles(conn, handles=handles, official_urls=source_paths)
    if not doc_ids:
        return {"documents": 0, "chunks": 0, "entities": 0}
    cleared = await clear_document_payload(
        conn,
        doc_ids,
        filenames=[official_document_filename(handle) for handle in handles],
        source_paths=source_paths,
    )
    await conn.execute("DELETE FROM documents WHERE id = ANY($1::int[])", doc_ids)
    return {
        "documents": len(doc_ids),
        "chunks": cleared["chunks"],
        "entities": cleared["entities"],
    }


async def prepare_rebuild(conn, *, request: ExtractRequest, files: Sequence[Path]) -> Optional[str]:
    if normalize_rebuild_mode(request.rebuild_mode) not in {"rechunk", "full"}:
        return None
    if request_uses_virtual_sources(request):
        rows = await conn.fetch("SELECT product_handle FROM official_product_profiles WHERE COALESCE(is_active, TRUE) = TRUE")
        handles = [str(row["product_handle"]) for row in rows if str(row["product_handle"] or "").strip()]
        docs = await find_existing_official_documents(conn, handles)
        backup_dir = await backup_official_snapshot(conn, handles=handles, docs=docs)
        await delete_existing_official_documents(conn, handles=handles, docs=docs)
        return backup_dir
    docs = await find_existing_documents(conn, files)
    backup_dir = await backup_snapshot(conn, files=files, docs=docs)
    await delete_existing_documents(conn, files=files, docs=docs)
    return backup_dir


async def process_pdf_file(conn, file_path: Path, *, job_id: Optional[str] = None) -> Dict[str, Any]:
    signature = compute_file_signature(file_path)
    source_path = str(file_path.resolve())
    doc_meta = document_meta_for(file_path)
    doc_meta.update(
        {
            "filesize": signature.get("filesize"),
            "file_mtime": signature.get("file_mtime").isoformat() if signature.get("file_mtime") else None,
        }
    )
    doc_id, doc_status = await upsert_document(
        conn,
        file_path.name,
        doc_meta,
        checksum=signature.get("checksum"),
        filesize=signature.get("filesize"),
        file_mtime=signature.get("file_mtime"),
    )
    if doc_status == "unchanged":
        await log_ingest_result(conn, file_path.name, "skipped", "Skipped (checksum already ingested)", signature)
        return {"file": file_path.name, "status": "skipped", "detail": "checksum unchanged", "source_kind": "pdf"}

    if doc_status == "updated":
        await clear_document_payload(conn, [doc_id], filenames=[file_path.name], source_paths=[source_path])

    await mark_current_work(
        conn,
        job_id,
        current_file=file_path.name,
        current_source_kind="pdf",
        current_phase="chunking",
    )
    chunk_records = await asyncio.to_thread(build_pdf_chunk_records_sync, file_path)

    if chunk_records:
        total_chunks = len(chunk_records)
        await mark_current_work(
            conn,
            job_id,
            current_file=file_path.name,
            current_source_kind="pdf",
            current_phase="embedding",
            current_items_done=0,
            current_items_total=total_chunks,
            current_chunks_done=0,
            current_records_done=None,
        )
        async def _pdf_embed_progress(done: int, total: int) -> None:
            await mark_current_work(
                conn,
                job_id,
                current_file=file_path.name,
                current_source_kind="pdf",
                current_phase="embedding",
                current_items_done=done,
                current_items_total=total,
                current_chunks_done=done,
                current_records_done=None,
            )

        await batch_embed_async(chunk_records, on_batch_done=_pdf_embed_progress)
        await mark_current_work(
            conn,
            job_id,
            current_file=file_path.name,
            current_source_kind="pdf",
            current_phase="indexing",
            current_items_done=total_chunks,
            current_items_total=total_chunks,
            current_chunks_done=total_chunks,
            current_records_done=None,
        )
        chunk_ids = await insert_chunks(conn, doc_id, chunk_records)
        await insert_entities(conn, chunk_ids, [chunk.get("entities") or [] for chunk in chunk_records])
        await insert_alias(conn, dedupe_alias_rows(chunk_records))

    detail = f"{len(chunk_records)} chunks indexed"
    await log_ingest_result(conn, file_path.name, "completed", detail, signature)
    return {
        "file": file_path.name,
        "status": "completed",
        "chunks": len(chunk_records),
        "source_kind": "pdf",
        "document_status": doc_status,
    }


async def process_spreadsheet_file(conn, file_path: Path, *, job_id: Optional[str] = None) -> Dict[str, Any]:
    signature = compute_file_signature(file_path)
    source_path = str(file_path.resolve())
    doc_meta = document_meta_for(file_path)
    doc_meta.update(
        {
            "filesize": signature.get("filesize"),
            "file_mtime": signature.get("file_mtime").isoformat() if signature.get("file_mtime") else None,
        }
    )
    doc_id, doc_status = await upsert_document(
        conn,
        file_path.name,
        doc_meta,
        checksum=signature.get("checksum"),
        filesize=signature.get("filesize"),
        file_mtime=signature.get("file_mtime"),
    )
    if doc_status == "unchanged":
        has_chunks = await spreadsheet_has_chunks(conn, document_id=doc_id, source_file=file_path.name)
        if has_chunks:
            await log_ingest_result(conn, file_path.name, "skipped", "Skipped (checksum already ingested)", signature)
            return {"file": file_path.name, "status": "skipped", "detail": "checksum unchanged", "source_kind": "spreadsheet"}
        doc_status = "updated"

    if doc_status == "updated":
        await clear_document_payload(conn, [doc_id], filenames=[file_path.name], source_paths=[source_path])

    await mark_current_work(
        conn,
        job_id,
        current_file=file_path.name,
        current_source_kind="spreadsheet",
        current_phase="loading",
    )
    _, chunk_records = await asyncio.to_thread(build_spreadsheet_records_sync, file_path)
    if not chunk_records:
        await delete_documents_by_ids(conn, [doc_id], filenames=[file_path.name])
        await log_ingest_result(conn, file_path.name, "skipped", "No knowledge rows found", signature)
        return {"file": file_path.name, "status": "skipped", "detail": "no knowledge rows", "source_kind": "spreadsheet"}

    total_chunks = len(chunk_records)
    await mark_current_work(
        conn,
        job_id,
        current_file=file_path.name,
        current_source_kind="spreadsheet",
        current_phase="embedding",
        current_items_done=0,
        current_items_total=total_chunks,
        current_chunks_done=0,
        current_records_done=0,
    )
    async def _spreadsheet_embed_progress(done: int, total: int) -> None:
        await mark_current_work(
            conn,
            job_id,
            current_file=file_path.name,
            current_source_kind="spreadsheet",
            current_phase="embedding",
            current_items_done=done,
            current_items_total=total,
            current_chunks_done=done,
            current_records_done=0,
        )

    await batch_embed_async(chunk_records, on_batch_done=_spreadsheet_embed_progress)
    await mark_current_work(
        conn,
        job_id,
        current_file=file_path.name,
        current_source_kind="spreadsheet",
        current_phase="indexing",
        current_items_done=total_chunks,
        current_items_total=total_chunks,
        current_chunks_done=total_chunks,
        current_records_done=0,
    )
    chunk_ids = await insert_chunks(conn, doc_id, chunk_records)
    await insert_entities(conn, chunk_ids, [chunk.get("entities") or [] for chunk in chunk_records])
    await insert_alias(conn, dedupe_alias_rows(chunk_records))
    detail = f"{len(chunk_records)} chunks indexed"
    await log_ingest_result(conn, file_path.name, "completed", detail, signature)
    return {
        "file": file_path.name,
        "status": "completed",
        "chunks": len(chunk_records),
        "records": 0,
        "source_kind": "spreadsheet",
        "document_status": doc_status,
    }


async def fetch_official_site_text(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, timeout=config.OFFICIAL_REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


async def hydrate_official_product(
    conn,
    client: httpx.AsyncClient,
    *,
    product_url: str,
    search_terms: List[str],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    await mark_current_work(
        conn,
        job_id,
        current_file=product_url,
        current_source_kind="official_site",
        current_phase="hydrating",
    )
    html = await fetch_official_site_text(client, product_url)
    profile = build_profile_from_product_page(
        base_url=config.OFFICIAL_BASE_URL,
        product_url=product_url,
        html=html,
        search_terms=search_terms,
    )
    if not profile:
        return {"url": product_url, "status": "skipped", "detail": "product json not found"}

    filename = official_document_filename(str(profile.get("product_handle") or ""))
    doc_meta = official_document_meta(profile)
    checksum = str(profile.get("product_json_hash") or "")
    doc_id, doc_status = await upsert_document(
        conn,
        filename,
        doc_meta,
        checksum=checksum or None,
        filesize=len(html.encode("utf-8")),
        file_mtime=utcnow(),
    )
    if doc_status == "unchanged":
        await upsert_official_product_profile(conn, profile)
        await sync_official_brand_domain(conn, profile)
        await log_ingest_result(
            conn,
            filename,
            "skipped",
            "Skipped (checksum already ingested)",
            {"checksum": checksum, "filesize": len(html.encode("utf-8")), "file_mtime": utcnow()},
        )
        return {
            "file": filename,
            "status": "skipped",
            "detail": "checksum unchanged",
            "source_kind": "official_site",
            "product_handle": profile.get("product_handle"),
            "official_url": profile.get("official_url"),
        }
    if doc_status == "updated":
        await clear_document_payload(conn, [doc_id], filenames=[filename], source_paths=[str(profile.get("official_url") or "")])
        await delete_official_product_profiles(conn, handles=[str(profile.get("product_handle") or "")], official_urls=[str(profile.get("official_url") or "")])

    chunk_payloads = build_profile_chunks(profile)
    chunk_records: List[Dict[str, Any]] = []
    for chunk_idx, payload in enumerate(chunk_payloads):
        chunk_records.append(
            build_chunk_record(
                chunk_idx=chunk_idx,
                text=str(payload.get("text") or ""),
                base_meta=dict(payload.get("meta") or {}),
                alias_source=str(profile.get("official_url") or ""),
            )
        )

    if chunk_records:
        total_chunks = len(chunk_records)
        await mark_current_work(
            conn,
            job_id,
            current_file=filename,
            current_source_kind="official_site",
            current_phase="embedding",
            current_items_done=0,
            current_items_total=total_chunks,
            current_chunks_done=0,
            current_records_done=None,
        )
        async def _official_embed_progress(done: int, total: int) -> None:
            await mark_current_work(
                conn,
                job_id,
                current_file=filename,
                current_source_kind="official_site",
                current_phase="embedding",
                current_items_done=done,
                current_items_total=total,
                current_chunks_done=done,
                current_records_done=None,
            )
        await batch_embed_async(chunk_records, on_batch_done=_official_embed_progress)
        await mark_current_work(
            conn,
            job_id,
            current_file=filename,
            current_source_kind="official_site",
            current_phase="indexing",
            current_items_done=total_chunks,
            current_items_total=total_chunks,
            current_chunks_done=total_chunks,
            current_records_done=None,
        )
        chunk_ids = await insert_chunks(conn, doc_id, chunk_records)
        await insert_entities(conn, chunk_ids, [chunk.get("entities") or [] for chunk in chunk_records])
        await insert_alias(conn, dedupe_alias_rows(chunk_records))

    await upsert_official_product_profile(conn, profile)
    await sync_official_brand_domain(conn, profile)
    await log_ingest_result(
        conn,
        filename,
        "completed",
        f"{len(chunk_records)} chunks indexed",
        {"checksum": checksum, "filesize": len(html.encode('utf-8')), "file_mtime": utcnow()},
    )
    return {
        "file": filename,
        "status": "completed",
        "chunks": len(chunk_records),
        "source_kind": "official_site",
        "document_status": doc_status,
        "product_handle": profile.get("product_handle"),
        "official_url": profile.get("official_url"),
    }


async def process_official_site_seed(
    conn,
    client: httpx.AsyncClient,
    seed: OfficialSiteSeed,
    *,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    if seed.seed_type == "product":
        result = await hydrate_official_product(conn, client, product_url=seed.value, search_terms=[seed.value], job_id=job_id)
        await asyncio.sleep(official_site_delay_seconds())
        return result

    await mark_current_work(
        conn,
        job_id,
        current_file=seed.value,
        current_source_kind="official_site",
        current_phase="discovery",
    )
    html = await fetch_official_site_text(client, seed.value)
    candidates = parse_discovery_html(config.OFFICIAL_BASE_URL, html)
    if not candidates:
        return {
            "file": seed.value,
            "status": "skipped",
            "detail": "no product candidates found",
            "source_kind": "official_site_discovery",
        }

    results: List[Dict[str, Any]] = []
    success = 0
    skipped = 0
    failed = 0
    total_candidates = len(candidates)
    for candidate in candidates:
        try:
            result = await hydrate_official_product(
                conn,
                client,
                product_url=str(candidate.get("official_url") or ""),
                search_terms=[term for term in [seed.query, seed.value] if term],
                job_id=job_id,
            )
        except Exception as exc:
            failed += 1
            result = {"status": "failed", "official_url": candidate.get("official_url"), "error": str(exc)}
        results.append(result)
        if result.get("status") == "completed":
            success += 1
        elif result.get("status") == "skipped":
            skipped += 1
        else:
            failed += 1
        await mark_current_work(
            conn,
            job_id,
            current_file=seed.value,
            current_source_kind="official_site",
            current_phase="hydrating",
            current_items_done=len(results),
            current_items_total=total_candidates,
            current_chunks_done=None,
            current_records_done=success,
        )
        await asyncio.sleep(official_site_delay_seconds())
    return {
        "file": seed.value,
        "status": "completed" if failed == 0 else "failed",
        "source_kind": "official_site_discovery",
        "detail": f"{success} products indexed, {skipped} skipped, {failed} failed",
        "products_indexed": success,
        "products_skipped": skipped,
        "products_failed": failed,
        "discovered_products": len(candidates),
        "seed_type": seed.seed_type,
    }


async def update_job_progress(conn, job_id: Optional[str], **fields: Any) -> None:
    if not job_id or not fields:
        return
    assignments: List[str] = []
    values: List[Any] = []
    for index, (key, value) in enumerate(fields.items(), start=1):
        if key in {"summary", "request_payload"}:
            assignments.append(f"{key} = ${index}::jsonb")
            values.append(json.dumps(value, ensure_ascii=False))
        else:
            assignments.append(f"{key} = ${index}")
            values.append(value)
    values.append(job_id)
    query = f"UPDATE extract_jobs SET {', '.join(assignments)} WHERE id = ${len(values)}::uuid"
    await conn.execute(query, *values)


async def get_job_summary(conn, job_id: Optional[str]) -> Dict[str, Any]:
    if not job_id:
        return {}
    row = await conn.fetchrow("SELECT summary FROM extract_jobs WHERE id = $1::uuid", job_id)
    if not row:
        return {}
    summary = row["summary"]
    if isinstance(summary, str):
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            summary = {}
    return dict(summary or {})


async def merge_job_summary(conn, job_id: Optional[str], **fields: Any) -> None:
    if not job_id:
        return
    summary = await get_job_summary(conn, job_id)
    for key, value in fields.items():
        summary[key] = value
    await update_job_progress(conn, job_id, summary=summary)


async def mark_current_work(
    conn,
    job_id: Optional[str],
    *,
    current_file: str,
    current_source_kind: str,
    current_phase: str,
    current_items_done: Optional[int] = None,
    current_items_total: Optional[int] = None,
    current_chunks_done: Optional[int] = None,
    current_records_done: Optional[int] = None,
) -> None:
    await merge_job_summary(
        conn,
        job_id,
        current_file=current_file,
        current_source_kind=current_source_kind,
        current_phase=current_phase,
        current_items_done=current_items_done,
        current_items_total=current_items_total,
        current_chunks_done=current_chunks_done,
        current_records_done=current_records_done,
    )


async def run_extract_request(request: ExtractRequest, *, job_id: Optional[str] = None) -> Dict[str, Any]:
    virtual_scope = request_uses_virtual_sources(request)
    seeds = await collect_official_site_seeds(request) if virtual_scope else []
    files = [] if virtual_scope else collect_source_files(request)
    total_items = len(seeds) if virtual_scope else len(files)
    if total_items == 0:
        result = {"ok": False, "msg": "no files found for extract request", "request": request.model_dump()}
        if job_id:
            conn = await db.get_conn()
            try:
                await update_job_progress(
                    conn,
                    job_id,
                    status="failed",
                    finished_at=utcnow(),
                    worker_id=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    error="no files found",
                    summary=result,
                )
            finally:
                await conn.close()
        return result

    conn = await db.get_conn()
    try:
        if job_id:
            await update_job_progress(
                conn,
                job_id,
                status="running",
                total_files=total_items,
                processed_files=0,
                success_files=0,
                failed_files=0,
                error=None,
            )

        backup_dir = await prepare_rebuild(conn, request=request, files=files)
        results: List[Dict[str, Any]] = []
        success_files = 0
        failed_files = 0
        if virtual_scope:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": "YS AI-OfficialSiteIngest/1.0"},
            ) as client:
                for index, seed in enumerate(seeds, start=1):
                    try:
                        result = await process_official_site_seed(conn, client, seed, job_id=job_id)
                        if result.get("status") == "failed":
                            failed_files += 1
                        elif result.get("status") == "completed":
                            success_files += 1
                    except Exception as exc:
                        logger.exception("Official site extract failed for %s", seed.value)
                        failed_files += 1
                        result = {"file": seed.value, "status": "failed", "error": str(exc), "source_kind": "official_site"}
                    results.append(result)
                    if job_id:
                        await update_job_progress(
                            conn,
                            job_id,
                            processed_files=index,
                            success_files=success_files,
                            failed_files=failed_files,
                        )
                        await merge_job_summary(conn, job_id, last_result=result)
        else:
            for index, file_path in enumerate(files, start=1):
                try:
                    kind = classify_source_kind(file_path)
                    if kind == "pdf":
                        result = await process_pdf_file(conn, file_path, job_id=job_id)
                    elif kind == "spreadsheet":
                        result = await process_spreadsheet_file(conn, file_path, job_id=job_id)
                    else:
                        result = {"file": file_path.name, "status": "skipped", "detail": f"unsupported type: {kind}"}
                    if result.get("status") == "failed":
                        failed_files += 1
                    elif result.get("status") == "completed":
                        success_files += 1
                except Exception as exc:
                    logger.exception("Extract failed for %s", file_path)
                    failed_files += 1
                    signature = compute_file_signature(file_path)
                    await log_ingest_result(conn, file_path.name, "failed", str(exc), signature)
                    result = {"file": file_path.name, "status": "failed", "error": str(exc)}
                results.append(result)
                if job_id:
                    await update_job_progress(
                        conn,
                        job_id,
                        processed_files=index,
                        success_files=success_files,
                        failed_files=failed_files,
                    )
                    await merge_job_summary(conn, job_id, last_result=result)

        summary = {
            "total_files": total_items,
            "processed_files": len(results),
            "success_files": success_files,
            "failed_files": failed_files,
            "backup_dir": backup_dir,
            "request": request.model_dump(),
            "last_result": results[-1] if results else None,
            "current_file": None,
            "current_source_kind": None,
            "current_phase": None,
            "current_items_done": None,
            "current_items_total": None,
            "current_chunks_done": None,
            "current_records_done": None,
        }
        payload = {"ok": failed_files == 0, "results": results, "summary": summary}
        if job_id:
            await update_job_progress(
                conn,
                job_id,
                status="succeeded" if failed_files == 0 else "failed",
                finished_at=utcnow(),
                processed_files=len(results),
                success_files=success_files,
                failed_files=failed_files,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                summary=summary,
                error=None if failed_files == 0 else "one or more files failed",
            )
        return payload
    finally:
        await conn.close()


def coerce_jsonlike(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def serialize_job_row(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row)
    for key in ("file_types", "input_roots", "request_payload", "summary"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                payload[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return payload


def _summary_has_current_progress(summary: Dict[str, Any]) -> bool:
    return any(
        summary.get(key) not in (None, "", [], {})
        for key in (
            "current_file",
            "current_phase",
            "current_items_done",
            "current_items_total",
            "current_chunks_done",
            "current_records_done",
        )
    )


def _current_file_from_job_payload(job: Dict[str, Any]) -> Optional[Path]:
    request_payload = job.get("request_payload") or {}
    if not isinstance(request_payload, dict):
        return None
    try:
        request = normalize_extract_request(ExtractRequest(**request_payload))
    except Exception:
        return None
    if request_uses_virtual_sources(request):
        return None
    files = collect_source_files(request)
    if not files:
        return None
    processed = int(job.get("processed_files") or 0)
    if processed < 0:
        processed = 0
    index = min(processed, len(files) - 1)
    return files[index]


async def enrich_job_with_db_fallback(conn, job: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(job.get("summary") or {})
    if _summary_has_current_progress(summary):
        return job
    if job.get("status") not in {"running", "queued"}:
        return job

    current_file = _current_file_from_job_payload(job)
    if not current_file:
        return job

    source_kind = classify_source_kind(current_file)
    filename = current_file.name
    chunks_done = 0
    records_done = None
    current_items_done = None
    current_items_total = None

    chunk_row = await conn.fetchrow(
        """
        SELECT COUNT(*) AS count
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.filename = $1
        """,
        filename,
    )
    chunks_done = int((chunk_row["count"] if chunk_row else 0) or 0)

    if source_kind == "spreadsheet":
        records_done = 0
        current_items_done = chunks_done
    elif source_kind == "pdf":
        current_items_done = chunks_done
    else:
        current_items_done = chunks_done

    summary.update(
        {
            "current_file": filename,
            "current_source_kind": source_kind,
            "current_phase": "legacy_db_fallback",
            "current_items_done": current_items_done,
            "current_items_total": current_items_total,
            "current_chunks_done": chunks_done,
            "current_records_done": records_done,
        }
    )
    job["summary"] = summary
    return job


def resolve_worker_id() -> str:
    configured = str(config.EXTRACT_WORKER_ID or "").strip()
    return configured or socket.gethostname()


async def sweep_expired_jobs() -> None:
    conn = await db.get_conn()
    try:
        await conn.execute(
            """
            UPDATE extract_jobs
            SET
                status = CASE
                    WHEN COALESCE(attempt_count, 0) >= COALESCE(max_attempts, $1) THEN 'failed'
                    ELSE 'queued'
                END,
                worker_id = NULL,
                heartbeat_at = NULL,
                lease_expires_at = NULL,
                started_at = CASE
                    WHEN COALESCE(attempt_count, 0) >= COALESCE(max_attempts, $1) THEN started_at
                    ELSE NULL
                END,
                finished_at = CASE
                    WHEN COALESCE(attempt_count, 0) >= COALESCE(max_attempts, $1) THEN NOW()
                    ELSE NULL
                END,
                error = CASE
                    WHEN COALESCE(attempt_count, 0) >= COALESCE(max_attempts, $1) THEN 'job lease expired and max attempts reached'
                    ELSE 'job lease expired; requeued'
                END
            WHERE status = 'running'
              AND (
                    lease_expires_at IS NULL
                 OR lease_expires_at < NOW()
              )
            """,
            config.EXTRACT_JOB_MAX_ATTEMPTS,
        )
    finally:
        await conn.close()


async def claim_next_job(worker_id: str) -> Optional[Dict[str, Any]]:
    conn = await db.get_conn()
    try:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                WITH candidate AS (
                    SELECT id
                    FROM extract_jobs
                    WHERE status = 'queued'
                      AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, $1)
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE extract_jobs job
                SET
                    status = 'running',
                    worker_id = $2,
                    started_at = NOW(),
                    heartbeat_at = NOW(),
                    lease_expires_at = NOW() + ($3 * INTERVAL '1 second'),
                    attempt_count = COALESCE(job.attempt_count, 0) + 1,
                    max_attempts = COALESCE(job.max_attempts, $1),
                    error = NULL,
                    finished_at = NULL
                WHERE job.id IN (SELECT id FROM candidate)
                RETURNING *
                """,
                config.EXTRACT_JOB_MAX_ATTEMPTS,
                worker_id,
                config.EXTRACT_JOB_LEASE_SECONDS,
            )
        return dict(row) if row else None
    finally:
        await conn.close()


async def heartbeat_job(job_id: str, worker_id: str) -> None:
    conn = await db.get_conn()
    try:
        await conn.execute(
            """
            UPDATE extract_jobs
            SET heartbeat_at = NOW(),
                lease_expires_at = NOW() + ($1 * INTERVAL '1 second')
            WHERE id = $2::uuid
              AND status = 'running'
              AND worker_id = $3
            """,
            config.EXTRACT_JOB_LEASE_SECONDS,
            job_id,
            worker_id,
        )
    finally:
        await conn.close()


async def heartbeat_loop(job_id: str, worker_id: str, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=config.EXTRACT_JOB_HEARTBEAT_SECONDS)
            break
        except asyncio.TimeoutError:
            try:
                await heartbeat_job(job_id, worker_id)
            except Exception:
                logger.exception("Extract job heartbeat failed for %s", job_id)


async def run_extract_worker(stop_event: asyncio.Event) -> None:
    worker_id = resolve_worker_id()
    while not stop_event.is_set():
        processed = False
        try:
            await sweep_expired_jobs()
            job = await claim_next_job(worker_id)
            if job:
                processed = True
                job_id = str(job["id"])
                request_payload = coerce_jsonlike(job.get("request_payload"), {})
                if not isinstance(request_payload, dict):
                    raise ValueError("extract job request payload is invalid")
                request = ExtractRequest(**request_payload)
                heartbeat_stop = asyncio.Event()
                heartbeat_task = asyncio.create_task(
                    heartbeat_loop(job_id, worker_id, heartbeat_stop),
                    name=f"extract-job-heartbeat:{job_id}",
                )
                try:
                    await run_extract_request(request, job_id=job_id)
                except Exception as exc:
                    logger.exception("Extract worker failed for job %s", job_id)
                    conn = await db.get_conn()
                    try:
                        await update_job_progress(
                            conn,
                            job_id,
                            status="failed",
                            finished_at=utcnow(),
                            worker_id=None,
                            heartbeat_at=None,
                            lease_expires_at=None,
                            error=str(exc),
                        )
                    finally:
                        await conn.close()
                finally:
                    heartbeat_stop.set()
                    try:
                        await heartbeat_task
                    except Exception:
                        logger.exception("Extract heartbeat join failed for %s", job_id)
        except Exception:
            logger.exception("Extract worker loop failed")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=1 if processed else config.EXTRACT_JOB_POLL_SECONDS,
            )
        except asyncio.TimeoutError:
            continue


async def enqueue_extract_job(request: ExtractRequest) -> Dict[str, Any]:
    total_items = await count_extract_work_items(request)
    if total_items == 0:
        return {"ok": False, "msg": "no files found for extract request", "request": request.model_dump()}

    conn = await db.get_conn()
    try:
        job_id = str(uuid.uuid4())
        queued_at = utcnow()
        request_payload = request.model_dump()
        await conn.execute(
            """
            INSERT INTO extract_jobs (
                id, job_type, source_scope, file_types, rebuild_mode, input_roots, status,
                requested_by, total_files, processed_files, success_files, failed_files,
                request_payload, worker_id, heartbeat_at, lease_expires_at, attempt_count, max_attempts,
                created_at
            )
            VALUES (
                $1::uuid, 'extract', $2, $3::jsonb, $4, $5::jsonb, 'queued', $6, $7, 0, 0, 0,
                $8::jsonb, NULL, NULL, NULL, 0, $9, $10
            )
            """,
            job_id,
            request.source_scope,
            json.dumps(request.file_types, ensure_ascii=False),
            request.rebuild_mode,
            json.dumps(request.input_roots, ensure_ascii=False),
            request.requested_by,
            total_items,
            json.dumps(request_payload, ensure_ascii=False),
            config.EXTRACT_JOB_MAX_ATTEMPTS,
            queued_at,
        )
    finally:
        await conn.close()

    return {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "queued_at": queued_at.isoformat(),
        "request": request_payload,
        "total_files": total_items,
    }


async def list_jobs(limit: int) -> List[Dict[str, Any]]:
    conn = await db.get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT *
            FROM extract_jobs
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        jobs = []
        for row in rows:
            jobs.append(await enrich_job_with_db_fallback(conn, serialize_job_row(dict(row))))
    finally:
        await conn.close()
    return jobs


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = await db.get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM extract_jobs WHERE id = $1::uuid", job_id)
        if row:
            return await enrich_job_with_db_fallback(conn, serialize_job_row(dict(row)))
    finally:
        await conn.close()
    return None


async def transition_job_status(job_id: str, *, from_status: str, to_status: str, clear_error: bool = False) -> Dict[str, Any]:
    conn = await db.get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM extract_jobs WHERE id = $1::uuid", job_id)
        if not row:
            return {"ok": False, "status_code": 404, "error": "extract job not found"}
        current = dict(row)
        if current.get("status") != from_status:
            return {
                "ok": False,
                "status_code": 409,
                "error": f"extract job must be {from_status} to transition to {to_status}",
                "job": serialize_job_row(current),
            }

        updates: Dict[str, Any] = {
            "status": to_status,
            "worker_id": None,
            "heartbeat_at": None,
            "lease_expires_at": None,
        }
        if to_status == "queued":
            updates.update(
                {
                    "started_at": None,
                    "finished_at": None,
                    "processed_files": 0,
                    "success_files": 0,
                    "failed_files": 0,
                    "summary": None,
                }
            )
        if clear_error:
            updates["error"] = None
        await update_job_progress(conn, job_id, **updates)
        fresh = await conn.fetchrow("SELECT * FROM extract_jobs WHERE id = $1::uuid", job_id)
    finally:
        await conn.close()

    return {"ok": True, "job": serialize_job_row(dict(fresh))}


async def pause_job(job_id: str) -> Dict[str, Any]:
    return await transition_job_status(job_id, from_status="queued", to_status="paused")


async def resume_job(job_id: str) -> Dict[str, Any]:
    return await transition_job_status(job_id, from_status="paused", to_status="queued", clear_error=True)


async def retry_job(job_id: str) -> Dict[str, Any]:
    return await transition_job_status(job_id, from_status="failed", to_status="queued", clear_error=True)
