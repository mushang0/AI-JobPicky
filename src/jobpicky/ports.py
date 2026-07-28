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
    MatchAssessment,
    Page,
    ProfileDraft,
    ProfileSnapshot,
    RecommendationItem,
    RunAccepted,
    RunView,
    SearchHit,
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


class ProfileParserPort(Protocol):
    async def parse(self, resume_text: str, extra_request: str | None) -> ProfileDraft: ...


class JobEvaluatorPort(Protocol):
    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
    ) -> list[MatchAssessment]: ...


class CrawlOrchestratorPort(Protocol):
    async def start(
        self,
        admin_id: str,
        source_ids: Sequence[str],
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def get_run(self, admin_id: str, run_id: str) -> RunView: ...


class RecommendationOrchestratorPort(Protocol):
    async def start(
        self,
        user_id: str,
        profile_id: str,
        extra_request: str | None = None,
        idempotency_key: str | None = None,
    ) -> RunAccepted: ...

    async def get_run(self, user_id: str, run_id: str) -> RunView: ...

    async def get_results(
        self,
        user_id: str,
        run_id: str,
        page: int,
        page_size: int,
    ) -> Page[RecommendationItem]: ...


__all__ = [
    "CrawlOrchestratorPort",
    "JobCatalogPort",
    "JobEvaluatorPort",
    "ProfileParserPort",
    "RecommendationOrchestratorPort",
    "SourceCollectorPort",
]
