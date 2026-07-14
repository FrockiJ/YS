import re
from typing import Any, Dict, List

from ..nlp.embedder import EmbeddingUnavailableError, embed_texts, embedding_model_name


def _to_pgvector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


QUALITY_SQL = """
    COALESCE(NULLIF(meta->>'content_quality', '')::double precision, 1.0) AS content_quality,
    COALESCE(NULLIF(meta->>'encoding_quality', '')::double precision, 1.0) AS encoding_quality,
    COALESCE(NULLIF(meta->>'is_garbled', '')::boolean, false) AS is_garbled
"""

NON_GARBLED_WHERE = "COALESCE(NULLIF(meta->>'is_garbled', '')::boolean, false) = false"
OCR_CONTENT_QUALITY_WHERE = """
    NOT (
        COALESCE(meta->>'source_family', '') = 'ocr_book_corpus'
        AND (
            char_length(BTRIM(text)) < 40
            OR COALESCE(NULLIF(meta->>'content_quality', '')::double precision, 1.0) < 0.2
            OR COALESCE(NULLIF(meta->>'encoding_quality', '')::double precision, 1.0) < 0.5
        )
    )
"""


async def vector_search(conn, query: str, k: int = 5) -> List[Dict[str, Any]]:
    try:
        qv = embed_texts([query])[0].tolist()
    except EmbeddingUnavailableError as exc:
        return await text_search(
            conn,
            query,
            k=k,
            embedding_error_type=exc.error_type,
            embedding_error_message=str(exc),
            embedding_model=exc.model or embedding_model_name(),
        )
    except Exception as exc:
        return await text_search(
            conn,
            query,
            k=k,
            embedding_error_type=type(exc).__name__,
            embedding_error_message=str(exc),
            embedding_model=embedding_model_name(),
        )
    vec_str = _to_pgvector_literal(qv)
    rows = await conn.fetch(
        f"""
        SELECT id, document_id, chunk_idx, text, summary, keywords,
               COALESCE(meta, '{{}}'::jsonb) || jsonb_build_object(
                   'retrieval_mode', 'vector',
                   'embedding_model', $3::text
               ) AS meta,
               kg,
               1 - (embedding <=> $1::vector) AS score,
               {QUALITY_SQL}
        FROM chunks
        WHERE {NON_GARBLED_WHERE}
          AND {OCR_CONTENT_QUALITY_WHERE}
        ORDER BY embedding <-> $1::vector,
                 COALESCE(NULLIF(meta->>'content_quality', '')::double precision, 1.0) DESC,
                 COALESCE(NULLIF(meta->>'encoding_quality', '')::double precision, 1.0) DESC
        LIMIT $2
    """,
        vec_str,
        k,
        embedding_model_name(),
    )
    return [dict(r) for r in rows]


def _text_search_terms(query: str) -> List[str]:
    terms: List[str] = []
    for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", str(query or "").lower()):
        if token.isdigit() and len(token) < 4:
            continue
        if len(token) < 2:
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= 5:
            break
    return terms


async def text_search(
    conn,
    query: str,
    k: int = 5,
    *,
    embedding_error_type: str = "",
    embedding_error_message: str = "",
    embedding_model: str = "",
) -> List[Dict[str, Any]]:
    terms = _text_search_terms(query)
    if not terms:
        return []
    clauses = []
    score_parts = []
    vals = []
    for term in terms:
        vals.append(f"%{term}%")
        idx = len(vals)
        clauses.append(f"(text ILIKE ${idx} OR summary ILIKE ${idx} OR meta::text ILIKE ${idx})")
        score_parts.append(
            f"""
            CASE
                WHEN text ILIKE ${idx} THEN 3.0
                WHEN summary ILIKE ${idx} THEN 2.0
                WHEN meta::text ILIKE ${idx} THEN 1.0
                ELSE 0.0
            END
            """
        )
    where = " AND ".join([NON_GARBLED_WHERE, OCR_CONTENT_QUALITY_WHERE, "(" + " OR ".join(clauses) + ")"])
    raw_term_score = " + ".join(score_parts) if score_parts else "0.0"
    term_score = (
        f"(({raw_term_score}) + "
        "CASE WHEN COALESCE(meta->>'source_family', '') = 'ocr_book_corpus' THEN 0.25 ELSE 0 END)"
    )
    vals.extend([
        embedding_error_type,
        embedding_error_message[:500],
        embedding_model or embedding_model_name(),
    ])
    error_type_idx = len(vals) - 2
    error_message_idx = len(vals) - 1
    model_idx = len(vals)
    limit_idx = len(vals) + 1
    rows = await conn.fetch(
        f"""
        SELECT id, document_id, chunk_idx, text, summary, keywords,
               COALESCE(meta, '{{}}'::jsonb) || jsonb_build_object(
                   'retrieval_mode', 'text_fallback',
                   'embedding_unavailable', true,
                   'embedding_error_type', ${error_type_idx}::text,
                   'embedding_error_message', ${error_message_idx}::text,
                   'embedding_model', ${model_idx}::text
               ) AS meta,
               kg,
               ({term_score})::double precision AS score,
               {QUALITY_SQL}
        FROM chunks
        WHERE {where}
        ORDER BY ({term_score}) DESC,
                 COALESCE(NULLIF(meta->>'content_quality', '')::double precision, 1.0) DESC,
                 COALESCE(NULLIF(meta->>'encoding_quality', '')::double precision, 1.0) DESC,
                 char_length(text) DESC,
                 id ASC
        LIMIT ${limit_idx}
    """,
        *vals,
        k,
    )
    return [dict(r) for r in rows]


async def structured_search(conn, filters: Dict[str, Any], k: int = 20) -> List[Dict[str, Any]]:
    clauses, vals = [NON_GARBLED_WHERE], []
    for key, val in filters.items():
        if val is None or val == "":
            continue
        options = []
        if isinstance(val, (list, tuple, set)):
            for entry in val:
                entry_str = str(entry).strip()
                if entry_str:
                    options.append(entry_str)
        else:
            entry_str = str(val).strip()
            if entry_str:
                options.append(entry_str)
        if not options:
            continue
        if len(options) == 1:
            clauses.append(f"meta->>'{key}' ILIKE ${len(vals)+1}")
            vals.append(f"%{options[0]}%")
        else:
            or_parts = []
            for entry in options:
                or_parts.append(f"meta->>'{key}' ILIKE ${len(vals)+1}")
                vals.append(f"%{entry}%")
            clauses.append("(" + " OR ".join(or_parts) + ")")
    where = " AND ".join(clauses) if clauses else "TRUE"
    limit_idx = len(vals) + 1
    sql = f"""
        SELECT id, document_id, chunk_idx, text, summary, keywords, meta, kg,
               {QUALITY_SQL}
        FROM chunks
        WHERE {where}
        ORDER BY COALESCE(NULLIF(meta->>'content_quality', '')::double precision, 1.0) DESC,
                 COALESCE(NULLIF(meta->>'encoding_quality', '')::double precision, 1.0) DESC,
                 id ASC
        LIMIT ${limit_idx}
    """
    rows = await conn.fetch(sql, *vals, k)
    return [dict(r) for r in rows]


async def year_filter_search(conn, year: int, k: int = 5):
    y = str(year)
    rows = await conn.fetch(
        """
        SELECT c.*, d.filename,
               COALESCE(NULLIF(c.meta->>'content_quality', '')::double precision, 1.0) AS content_quality,
               COALESCE(NULLIF(c.meta->>'encoding_quality', '')::double precision, 1.0) AS encoding_quality,
               COALESCE(NULLIF(c.meta->>'is_garbled', '')::boolean, false) AS is_garbled
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE COALESCE(NULLIF(c.meta->>'is_garbled', '')::boolean, false) = false
          AND c.text ILIKE $1
        ORDER BY c.id
        LIMIT $2
    """,
        f"%{y}%",
        k,
    )
    return [dict(r) for r in rows]
