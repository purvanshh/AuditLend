import os
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://auditlend:auditlend@postgres:5432/auditlend",
)
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://auditlend:auditlend@postgres:5432/auditlend",
)

sync_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
async_engine = create_async_engine(ASYNC_DATABASE_URL, pool_pre_ping=True)

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
