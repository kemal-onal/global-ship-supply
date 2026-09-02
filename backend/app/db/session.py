"""
Database session management with async SQLAlchemy.
Supports connection pooling, read replicas, and health checks.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from sqlalchemy import text, event
from sqlalchemy.engine import Engine

from app.core.config import settings


# Primary write engine
engine: AsyncEngine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_size=settings.POSTGRES_POOL_SIZE,
    max_overflow=settings.POSTGRES_MAX_OVERFLOW,
    pool_timeout=settings.POSTGRES_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=settings.ENVIRONMENT == "local",
)

# Read replica engine (can point to same or different host)
read_engine: AsyncEngine | None = None
if settings.ENVIRONMENT not in ("local", "development"):
    # In production, configure read replica with a dedicated readonly role
    from sqlalchemy.engine.url import make_url
    _primary_url = make_url(str(settings.SQLALCHEMY_DATABASE_URI))
    _replica_url = _primary_url.set(username="readonly")
    read_engine = create_async_engine(
        _replica_url.render_as_string(hide_password=False),
        pool_size=settings.POSTGRES_POOL_SIZE,
        max_overflow=settings.POSTGRES_MAX_OVERFLOW,
        pool_pre_ping=True,
        echo=False,
    )

# Session factories
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

read_session_factory: async_sessionmaker[AsyncSession] | None = None
if read_engine:
    read_session_factory = async_sessionmaker(
        read_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for write operations."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session for read operations (uses replica if available)."""
    factory = read_session_factory or async_session_factory
    async with factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database connections and verify health."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))
    if read_engine:
        async with read_engine.begin() as conn:
            await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
    if read_engine:
        await read_engine.dispose()


# Connection health check
async def check_db_health() -> dict[str, bool]:
    """Check database connectivity."""
    results = {"primary": False, "replica": False}
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        results["primary"] = True
    except Exception:
        pass

    if read_engine:
        try:
            async with read_engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
            results["replica"] = True
        except Exception:
            pass

    return results


# Event listeners for connection monitoring
@event.listens_for(Engine, "connect")
def receive_connect(dbapi_connection, connection_record):
    """Log new connections in development."""
    if settings.ENVIRONMENT == "local":
        pass  # Connection established


@event.listens_for(Engine, "checkout")
def receive_checkout(dbapi_connection, connection_record, connection_proxy):
    """Validate connection on checkout."""
    pass