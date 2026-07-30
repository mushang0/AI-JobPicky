from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from catalog.factories import make_job

from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.embedding_backfill import backfill_job_embeddings
from jobpicky.infrastructure.embeddings import LocalBGEEmbedding


class FakeEmbedding:
    dimension = 512

    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 511

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[1.0] + [0.0] * 511 for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.jobs = [make_job(id="job-1"), make_job(id="job-2", title="算法工程师")]
        self.embeddings: dict[str, list[float]] = {}

    async def get_jobs_without_embeddings(self, *, limit: int, offset: int = 0):
        return [job for job in self.jobs if job.id not in self.embeddings][:limit]

    async def save_embeddings(self, embeddings: Mapping[str, Sequence[float]]) -> None:
        self.embeddings.update({job_id: list(vector) for job_id, vector in embeddings.items()})


def test_backfill_uses_canonical_text_and_is_rerunnable() -> None:
    async def check() -> None:
        embedding = FakeEmbedding()
        store = FakeStore()
        first = await backfill_job_embeddings(embedding, store, batch_size=1)
        second = await backfill_job_embeddings(embedding, store, batch_size=1)

        assert first.processed == 2
        assert second.processed == 0
        assert len(store.embeddings) == 2
        assert "岗位名称：后端工程师" in embedding.texts[0]
        assert "工作地点：上海" in embedding.texts[0]
        assert all(len(vector) == 512 for vector in store.embeddings.values())

    asyncio.run(check())


def test_missing_model_path_is_an_explicit_dependency_error() -> None:
    async def check() -> None:
        try:
            await LocalBGEEmbedding(None).embed_query("后端工程师")
        except ApplicationError as exc:
            assert exc.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)
            assert exc.details.get("dependency") == "embedding"
        else:  # pragma: no cover - assertion branch
            raise AssertionError("missing model path must fail")

    asyncio.run(check())


def test_model_tokenizer_enforces_the_actual_token_budget() -> None:
    class FakeTokenizer:
        def encode(self, text: str, **_: object) -> list[int]:
            return list(range(len(text)))

        def decode(self, token_ids: Sequence[int], **_: object) -> str:
            return "a" * len(token_ids)

    class FakeModel:
        class Client:
            tokenizer = FakeTokenizer()

        client = Client()

    text = LocalBGEEmbedding._truncate_for_model(FakeModel(), "a" * 600)

    assert text == "a" * 512
