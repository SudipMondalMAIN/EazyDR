"""
Database engine/session setup. Postgres-only, provider-agnostic.
Swapping Supabase -> AWS RDS later requires changing only DATABASE_URL.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# pool_pre_ping avoids stale-connection errors on free-tier DBs that idle-drop.
# pool_size/max_overflow are here so horizontal scaling + connection pooling
# (PgBouncer in front, later) is a config change, not a code change.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
