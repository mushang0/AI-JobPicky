from __future__ import annotations

from collections.abc import Sequence

from ..contracts import (
    Candidate,
    HardFilterSpec,
    ProfileSnapshot,
    RetrievalChannel,
    SearchHit,
)
from .config import MatchingConfig
from .embedding_text import build_query_embedding_text


class BaselineMatchingService:
    """Deterministic baseline implementation of MatchingPort.

    Hard conditions stay fully deterministic (R3): natural-language input never
    turns into filter criteria, and missing profile information never counts
    against a job (R2).
    """

    def __init__(self, config: MatchingConfig | None = None) -> None:
        self._config = config or MatchingConfig()

    @property
    def config(self) -> MatchingConfig:
        return self._config

    def build_filter_spec(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> HardFilterSpec:
        # effective_extra_request is natural language; the baseline cannot
        # deterministically derive hard conditions from it.
        # graduation_year / min_salary pass through as-is: None means the
        # filter must not exclude on that dimension (R2), and jobs without
        # salary or graduation-year facts are never excluded either.
        return HardFilterSpec(
            target_locations=list(profile.target_locations),
            excluded_roles=list(profile.excluded_roles),
            education=profile.education,
            recruitment_types=list(profile.recruitment_types),
            graduation_year=profile.graduation_year,
            min_salary=profile.expected_salary_min,
            only_open=True,
        )

    def build_query_text(
        self,
        profile: ProfileSnapshot,
        effective_extra_request: str | None,
    ) -> str:
        # effective_extra_request is already merged at run creation
        # (architecture §4.12), so it is used as-is.
        parts = [
            *profile.target_roles,
            *profile.skills,
            profile.experience_summary,
            effective_extra_request,
        ]
        seen: set[str] = set()
        lines: list[str] = []
        for part in parts:
            if part is None:
                continue
            text = part.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            lines.append(text)
        return build_query_embedding_text(lines)

    def merge_candidates(
        self,
        keyword_hits: Sequence[SearchHit],
        semantic_hits: Sequence[SearchHit],
    ) -> list[Candidate]:
        keyword_scores = self._scores_by_job(keyword_hits, RetrievalChannel.KEYWORD)
        semantic_scores = self._scores_by_job(semantic_hits, RetrievalChannel.SEMANTIC)

        candidates: list[Candidate] = []
        for job_id in keyword_scores.keys() | semantic_scores.keys():
            keyword_score = keyword_scores.get(job_id)
            semantic_score = semantic_scores.get(job_id)
            retrieval_score = self._config.keyword_weight * (
                keyword_score or 0.0
            ) + self._config.semantic_weight * (semantic_score or 0.0)
            if retrieval_score < self._config.min_retrieval_score:
                continue
            sources = [
                channel
                for channel, score in (
                    (RetrievalChannel.KEYWORD, keyword_score),
                    (RetrievalChannel.SEMANTIC, semantic_score),
                )
                if score is not None
            ]
            candidates.append(
                Candidate(
                    job_id=job_id,
                    retrieval_score=retrieval_score,
                    keyword_score=keyword_score,
                    semantic_score=semantic_score,
                    sources=sources,
                )
            )

        # Score descending, job_id ascending as tie-breaker: reproducible.
        candidates.sort(key=lambda c: (-c.retrieval_score, c.job_id))
        return candidates[: self._config.max_candidates]

    @staticmethod
    def _scores_by_job(
        hits: Sequence[SearchHit],
        expected_channel: RetrievalChannel,
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        for hit in hits:
            if hit.channel != expected_channel:
                raise ValueError(
                    f"hit for job {hit.job_id} has channel {hit.channel}, "
                    f"expected {expected_channel}"
                )
            if hit.job_id in scores:
                raise ValueError(
                    f"duplicate hit for job {hit.job_id} in {expected_channel} results"
                )
            scores[hit.job_id] = hit.score
        return scores
