"""
SQLAlchemy async database setup.
Supports Neon Postgres (asyncpg) in production and SQLite (aiosqlite) locally.
Provides engine, session factory, and table initialization.
"""

import ssl as _ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.utils.config import DATABASE_URL

# Build engine kwargs; add SSL for Neon Postgres (asyncpg needs it via connect_args)
_engine_kwargs: dict = dict(
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=300,  # recycle connections every 5 min (Neon drops idle ones)
)

if DATABASE_URL.startswith("postgresql"):
    # asyncpg requires SSL context via connect_args, not URL query params
    _ssl_ctx = _ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = _ssl.CERT_NONE
    _engine_kwargs["connect_args"] = {"ssl": _ssl_ctx}

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

# Session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def init_db() -> None:
    """Create all tables if they don't exist yet."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Yield a database session for dependency injection."""
    async with async_session() as session:
        yield session
