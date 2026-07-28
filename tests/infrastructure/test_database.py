from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy import text

from jobpicky.infrastructure.database import create_engine

_TEST_DATABASE_URL = os.environ.get("JOBPICKY_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not _TEST_DATABASE_URL,
    reason="JOBPICKY_TEST_DATABASE_URL is not set; start the compose db and run migrations",
)


def test_engine_connects() -> None:
    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
        await engine.dispose()

    asyncio.run(check())


def test_pgvector_extension_installed() -> None:
    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            )
            assert result.scalar_one() == 1
        await engine.dispose()

    asyncio.run(check())


def test_job_table_exists_after_migration() -> None:
    async def check() -> None:
        engine = create_engine(_TEST_DATABASE_URL)
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT count(*) FROM information_schema.tables WHERE table_name = 'job'")
            )
            assert result.scalar_one() == 1
        await engine.dispose()

    asyncio.run(check())
