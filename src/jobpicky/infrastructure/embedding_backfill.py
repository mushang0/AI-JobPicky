from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from ..matching.embedding_text import build_job_embedding_text
from ..ports import EmbeddingPort, JobEmbeddingStorePort


@dataclass(frozen=True, slots=True)
class BackfillStats:
    processed: int = 0
    failed_batches: int = 0


async def backfill_job_embeddings(
    embedding: EmbeddingPort,
    store: JobEmbeddingStorePort,
    *,
    batch_size: int = 32,
    batch_timeout_seconds: float = 60.0,
    on_progress: Callable[[BackfillStats], None] | None = None,
) -> BackfillStats:
    """Fill only missing vectors; rerunning is therefore safe and idempotent."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if batch_timeout_seconds <= 0:
        raise ValueError("batch_timeout_seconds must be positive")

    stats = BackfillStats()
    while True:
        jobs = await store.get_jobs_without_embeddings(limit=batch_size)
        if not jobs:
            return stats
        texts = [build_job_embedding_text(job) for job in jobs]
        try:
            vectors = await asyncio.wait_for(
                embedding.embed_documents(texts),
                timeout=batch_timeout_seconds,
            )
            if len(vectors) != len(jobs):
                raise ValueError("embedding provider returned an invalid batch length")
            await store.save_embeddings(
                {job.id: vector for job, vector in zip(jobs, vectors, strict=True)}
            )
        except Exception:
            stats = BackfillStats(
                processed=stats.processed,
                failed_batches=stats.failed_batches + 1,
            )
            if on_progress is not None:
                on_progress(stats)
            raise
        stats = BackfillStats(processed=stats.processed + len(jobs))
        if on_progress is not None:
            on_progress(stats)


__all__ = ["BackfillStats", "backfill_job_embeddings"]
