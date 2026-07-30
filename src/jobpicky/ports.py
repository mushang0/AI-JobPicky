from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .contracts import (
    Candidate,
    CollectionBatch,
    FilterResult,
    HardFilterSpec,
    IngestionResult,
    JobFact,
    JobQuery,
    MatchAssessment,
    Page,
    ProfileDraft,
    ProfileSnapshot,
    RecommendationItem,
    RunAccepted,
    RunView,
    SearchHit,
    SourceInput,
    SourcePatch,
    SourceView,
)


class SourceCollectorPort(Protocol):
    async def collect(
        self,
        source: SourceView,
        *,
        config: Mapping[str, object] | None = None,
    ) -> CollectionBatch: ...


class JobCatalogPort(Protocol):
    async def ingest(self, run_id: str, batch: CollectionBatch) -> IngestionResult: ...

    async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]: ...

    async def hard_filter(self, spec: HardFilterSpec) -> FilterResult: ...

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]: ...

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]: ...


class EmbeddingPort(Protocol):
    """Async embedding boundary with a fixed 512-dimensional contract."""

    dimension: int

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class JobEmbeddingStorePort(Protocol):
    """Persistence boundary used by the explicit job embedding backfill."""

    async def get_jobs_without_embeddings(
        self,
        *,
        limit: int,
        offset: int = 0,
    ) -> list[JobFact]: ...

    async def save_embeddings(self, embeddings: Mapping[str, Sequence[float]]) -> None: ...


class ProfileParserPort(Protocol):
    async def parse(self, resume_text: str, extra_request: str | None) -> ProfileDraft: ...


class ProfileSnapshotReaderPort(Protocol):
    async def get_snapshot(self, user_id: str, profile_id: str) -> ProfileSnapshot: ...


class ProfileApplicationPort(Protocol):
    async def create_profile(
        self,
        user_id: str,
        *,
        resume_text: str,
        extra_request: str | None = None,
    ) -> ProfileSnapshot: ...

    async def get_current(self, user_id: str) -> ProfileSnapshot: ...

    async def update_profile(
        self,
        user_id: str,
        profile_id: str,
        draft: ProfileDraft,
    ) -> ProfileSnapshot: ...


class SourceApplicationPort(Protocol):
    async def create_source(self, admin_id: str, source: SourceInput) -> SourceView: ...

    async def list_sources(
        self,
        admin_id: str,
        page: int,
        page_size: int,
    ) -> Page[SourceView]: ...

    async def get_source(self, admin_id: str, source_id: str) -> SourceView: ...

    async def update_source(
        self,
        admin_id: str,
        source_id: str,
        patch: SourcePatch,
    ) -> SourceView: ...


class UserJobQueryPort(Protocol):
    async def get_job(self, user_id: str, job_id: str) -> JobFact: ...


class AdminJobQueryPort(Protocol):
    async def list_jobs(
        self,
        admin_id: str,
        query: JobQuery,
        page: int,
        page_size: int,
    ) -> Page[JobFact]: ...

    async def get_job(self, admin_id: str, job_id: str) -> JobFact: ...


class MatchingPort(Protocol):
    def build_filter_spec(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> HardFilterSpec: ...

    def build_query_text(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> str: ...

    def merge_candidates(
        self,
        keyword_hits: Sequence[SearchHit],
        semantic_hits: Sequence[SearchHit],
    ) -> list[Candidate]: ...


class JobEvaluatorPort(Protocol):
    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        effective_extra_request: str | None = None,
    ) -> list[MatchAssessment]: ...


class CrawlOrchestratorPort(Protocol):
    async def start(
        self,
        admin_id: str,
        source_ids: Sequence[str],
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def list_runs(
        self,
        admin_id: str,
        page: int,
        page_size: int,
    ) -> Page[RunView]: ...

    async def get_run(self, admin_id: str, run_id: str) -> RunView: ...


class RecommendationOrchestratorPort(Protocol):
    async def start(
        self,
        user_id: str,
        profile_id: str,
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def list_runs(
        self,
        user_id: str,
        page: int,
        page_size: int,
    ) -> Page[RunView]: ...

    async def get_run(self, user_id: str, run_id: str) -> RunView: ...

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationItem]: ...


class AdminRecommendationRunQueryPort(Protocol):
    async def list_runs(
        self,
        admin_id: str,
        page: int,
        page_size: int,
    ) -> Page[RunView]: ...

    async def get_run(self, admin_id: str, run_id: str) -> RunView: ...


__all__ = [
    "AdminJobQueryPort",
    "AdminRecommendationRunQueryPort",
    "CrawlOrchestratorPort",
    "EmbeddingPort",
    "JobCatalogPort",
    "JobEmbeddingStorePort",
    "JobEvaluatorPort",
    "MatchingPort",
    "ProfileApplicationPort",
    "ProfileParserPort",
    "ProfileSnapshotReaderPort",
    "RecommendationOrchestratorPort",
    "SourceApplicationPort",
    "SourceCollectorPort",
    "UserJobQueryPort",
]
