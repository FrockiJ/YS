from __future__ import annotations

import json
from typing import List, Dict, Any, Tuple

import numpy as np


def _vec_literal(v: np.ndarray) -> str:
    if isinstance(v, list):
        v = np.array(v, dtype=float)
    return "[" + ",".join(f"{float(x):.6f}" for x in v.tolist()) + "]"


async def upsert_document(
    conn,
    filename: str,
    meta: Dict[str, Any],
    checksum: str | None = None,
    filesize: int | None = None,
    file_mtime=None,
) -> Tuple[int, str]:
    meta_str = json.dumps(meta or {}, ensure_ascii=False)
    existing = None
    if checksum:
        existing = await conn.fetchrow(
            "SELECT id FROM documents WHERE filename=$1 AND checksum=$2 LIMIT 1",
            filename,
            checksum,
        )
    if existing:
        await conn.execute(
            """
            UPDATE documents SET meta=$2::jsonb, file_mtime=$3, filesize=$4
            WHERE id=$1
            """,
            existing["id"],
            meta_str,
            file_mtime,
            filesize,
        )
        return existing["id"], "unchanged"
    existing_filename = await conn.fetchrow(
        "SELECT id FROM documents WHERE filename=$1 LIMIT 1",
        filename,
    )
    if existing_filename:
        await conn.execute(
            """
            UPDATE documents
            SET filetype=$2, meta=$3::jsonb, file_mtime=$4, filesize=$5, checksum=$6
            WHERE id=$1
            """,
            existing_filename["id"],
            (meta or {}).get("filetype", "pdf"),
            meta_str,
            file_mtime,
            filesize,
            checksum,
        )
        return existing_filename["id"], "updated"
    rec = await conn.fetchrow(
        """
        INSERT INTO documents(filename, filetype, meta, file_mtime, filesize, checksum)
        VALUES($1,$2,$3::jsonb,$4,$5,$6) RETURNING id
        """,
        filename,
        (meta or {}).get("filetype", "pdf"),
        meta_str,
        file_mtime,
        filesize,
        checksum,
    )
    return rec["id"], "created"


async def insert_chunks(conn, document_id: int, chunks: List[Dict[str, Any]]) -> List[int]:
    chunk_ids: List[int] = []
    for c in chunks:
        meta_str = json.dumps(c.get("meta", {}) or {}, ensure_ascii=False)
        kg_payload = json.dumps(c.get("kg") or {"nodes": [], "edges": []}, ensure_ascii=False)
        keywords = c.get("keywords") or []
        summary = c.get("summary")
        vstr = _vec_literal(c["embedding"])
        rec = await conn.fetchrow(
            """
            INSERT INTO chunks(document_id, chunk_idx, text, summary, keywords, meta, kg, embedding)
            VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::vector)
            RETURNING id
            """,
            document_id,
            c["chunk_idx"],
            c["text"],
            summary,
            keywords,
            meta_str,
            kg_payload,
            vstr,
        )
        chunk_ids.append(rec["id"])
    return chunk_ids


async def insert_entities(conn, chunk_id_map: List[int], entities_per_chunk: List[List[Dict[str, Any]]]):
    for chunk_id, entity_list in zip(chunk_id_map, entities_per_chunk):
        if not entity_list:
            continue
        for ent in entity_list:
            meta = json.dumps(ent.get("meta") or {}, ensure_ascii=False)
            await conn.execute(
                """
                INSERT INTO entities(chunk_id, type, value, normalized, confidence, meta)
                VALUES ($1,$2,$3,$4,$5,$6::jsonb)
                """,
                chunk_id,
                ent.get("type"),
                ent.get("value"),
                ent.get("normalized"),
                ent.get("confidence", 0.8),
                meta,
            )


async def insert_alias(conn, alias_rows: List[Dict[str, Any]]):
    if not alias_rows:
        return
    canonicals = list({a["canonical"] for a in alias_rows if a.get("canonical")})
    existing = set()
    if canonicals:
        rows = await conn.fetch(
            "SELECT canonical, variant FROM alias WHERE canonical = ANY($1::text[])",
            canonicals,
        )
        existing = {(r["canonical"], r["variant"]) for r in rows}
    filtered = [
        a
        for a in alias_rows
        if (a["canonical"], a["variant"]) not in existing
    ]
    if not filtered:
        return
    for a in filtered:
        await conn.execute(
            """
            INSERT INTO alias(canonical, variant, type, lang, source, confidence)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT (canonical, variant) DO NOTHING
            """,
            a["canonical"],
            a["variant"],
            a.get("type"),
            a.get("lang"),
            a.get("source"),
            a.get("confidence", 0.5),
        )


async def delete_documents_by_ids(conn, document_ids: List[int], *, filenames: List[str] | None = None):
    ids = [int(document_id) for document_id in document_ids if document_id is not None]
    if not ids:
        return {"documents": 0, "chunks": 0, "entities": 0}

    cleared = await clear_document_payload(conn, ids, filenames=filenames)
    await conn.execute(
        "DELETE FROM documents WHERE id = ANY($1::int[])",
        ids,
    )
    return {
        "documents": len(ids),
        "chunks": cleared["chunks"],
        "entities": cleared["entities"],
    }


async def clear_document_payload(
    conn,
    document_ids: List[int],
    *,
    filenames: List[str] | None = None,
    source_paths: List[str] | None = None,
):
    ids = [int(document_id) for document_id in document_ids if document_id is not None]
    if not ids:
        return {"documents": 0, "chunks": 0, "entities": 0}

    chunk_rows = await conn.fetch(
        "SELECT id FROM chunks WHERE document_id = ANY($1::int[])",
        ids,
    )
    chunk_ids = [int(row["id"]) for row in chunk_rows]
    if chunk_ids:
        await conn.execute(
            "DELETE FROM entities WHERE chunk_id = ANY($1::int[])",
            chunk_ids,
        )
        await conn.execute(
            "DELETE FROM chunks WHERE id = ANY($1::int[])",
            chunk_ids,
        )
    if source_paths:
        normalized = [str(path) for path in source_paths if str(path).strip()]
        if normalized:
            await conn.execute(
                "DELETE FROM alias WHERE source = ANY($1::text[])",
                normalized,
            )
    if filenames:
        await conn.execute(
            "DELETE FROM ingest_log WHERE filename = ANY($1::text[])",
            [str(name) for name in filenames if str(name).strip()],
        )
    return {
        "documents": len(ids),
        "chunks": len(chunk_ids),
        "entities": len(chunk_ids),
    }
