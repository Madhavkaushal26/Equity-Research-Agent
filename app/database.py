"""Async database lifecycle and request-scoped transactions."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session


async def init_db() -> None:
    """Apply the bundled, idempotent DDL in one serialized transaction.

    The schema contains only plain DDL and line comments, with no procedural
    blocks or semicolons inside string literals.
    """
    schema = await asyncio.to_thread(
        (Path(__file__).resolve().parent.parent / "schema.sql").read_text,
        encoding="utf-8",
    )
    async with engine.begin() as connection:
        await connection.execute(text("SELECT pg_advisory_xact_lock(735126891)"))
        for statement in schema.split(";"):
            if statement.strip():
                await connection.exec_driver_sql(statement)
