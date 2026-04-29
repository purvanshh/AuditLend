import os
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://auditlend:auditlend@postgres:5432/auditlend",
)
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://auditlend:auditlend@postgres:5432/auditlend",
)

sync_engine = create_engine(DATABASE_URL, pool_pre_ping=True)

_async_engine_options = {"pool_pre_ping": True}
if os.getenv("AUDITLEND_ASYNC_DB_POOL", "pooled").lower() in {"null", "none", "disabled"}:
    # Some test clients exercise the ASGI app from multiple event loops. Async
    # connection pools are event-loop bound, so tests can opt into NullPool.
    _async_engine_options["poolclass"] = NullPool

async_engine = create_async_engine(ASYNC_DATABASE_URL, **_async_engine_options)

SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    autoflush=False,
)


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
