"""Database engine and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Resolve the DB path to absolute based on the project root
_db_url = settings.database.url
if "///." in _db_url:
    # Relative path like sqlite+aiosqlite:///./data/foo.db
    # Resolve relative to this file's parent's parent (project root)
    _project_root = Path(__file__).resolve().parent.parent
    _rel = _db_url.split("///./", 1)[1]
    _abs_path = _project_root / _rel
    _abs_path.parent.mkdir(parents=True, exist_ok=True)
    _db_url = f"sqlite+aiosqlite:///{_abs_path}"

engine = create_async_engine(_db_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        yield session
