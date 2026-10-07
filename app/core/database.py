from collections.abc import AsyncIterator
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
    # neon suspends idle computes, so don't keep connections around for too long
    pool_recycle=300,
    connect_args={
        # the neon pooler runs pgbouncer in transaction mode, asyncpg's statement
        # cache and sequential statement names don't play well with that
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """For websockets, which only need a session for a moment now and then. A session
    held for the whole connection would sit on a pooled connection for hours."""
    return SessionLocal
