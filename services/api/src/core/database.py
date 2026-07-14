from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import asynccontextmanager

from .config import PG

DATABASE_URL = f"postgresql+asyncpg://{PG['user']}:{PG['pw']}@{PG['host']}:{PG['port']}/{PG['db']}"

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()

@asynccontextmanager
async def get_async_session():
    async with SessionLocal() as session:
        yield session