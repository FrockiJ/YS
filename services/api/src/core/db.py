import asyncpg
from .config import PG
async def get_conn():
    return await asyncpg.connect(host=PG['host'], port=PG['port'], database=PG['db'], user=PG['user'], password=PG['pw'])
