from __future__ import annotations

import asyncio
import sys

from jobpicky.config import Settings
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.embedding_backfill import backfill_job_embeddings
from jobpicky.infrastructure.embeddings import LocalBGEEmbedding
from jobpicky.infrastructure.job_embedding_store import PostgresJobEmbeddingStore


async def _run() -> int:
    try:
        settings = Settings.from_env()
        if settings.embedding_model_path is None:
            raise ValueError("JOBPICKY_EMBEDDING_MODEL_PATH is required for embedding backfill")
        engine = create_engine(settings.database_url)
        embedding = LocalBGEEmbedding(
            settings.embedding_model_path,
            model_revision=settings.embedding_model_revision,
            query_timeout_seconds=settings.embedding_query_timeout_seconds,
            batch_timeout_seconds=settings.embedding_backfill_timeout_seconds,
        )
        store = PostgresJobEmbeddingStore(create_session_factory(engine))

        def report(stats: object) -> None:
            print(f"embedding backfill progress: {stats}")

        stats = await backfill_job_embeddings(
            embedding,
            store,
            batch_size=settings.embedding_batch_size,
            batch_timeout_seconds=settings.embedding_backfill_timeout_seconds,
            on_progress=report,
        )
        print(f"embedding backfill complete: {stats}")
        await engine.dispose()
        return 0
    except Exception as exc:
        print(f"embedding backfill failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
