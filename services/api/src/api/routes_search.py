from fastapi import APIRouter
from typing import Optional
from ..core import db
from ..pipelines.rag.searcher import vector_search, structured_search
from ..pipelines.compose.composer import compose_answer

router = APIRouter()

@router.get('/search')
async def search(q: Optional[str] = None,
                 region: Optional[str] = None,
                 village: Optional[str] = None,
                 vineyard: Optional[str] = None,
                 k: int = 5):
    conn = await db.get_conn()
    try:
        hits = []
        # structured first (if filters provided)
        if region or village or vineyard:
            filters = {'region': region, 'village': village, 'vineyard': vineyard}
            hits = await structured_search(conn, filters, k=k)

        # then vector
        if q:
            vhits = await vector_search(conn, q, k=k)
            ids = {h['id'] for h in hits}
            for h in vhits:
                if h['id'] not in ids:
                    hits.append(h)

        return {'ok': True, 'hits': hits}
    finally:
        await conn.close()

@router.get('/search/answer')
async def search_answer(q: str, k: int = 5):
    conn = await db.get_conn()
    try:
        hits = await vector_search(conn, q, k=k)
        composed = await compose_answer(q, hits) # <--- 改為呼叫 routes_chat 中的版本
        return composed
    finally:
        await conn.close()
