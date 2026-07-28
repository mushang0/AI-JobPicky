from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field, model_validator

from .catalog import JobFact, RetrievalChannel
from .common import ContractModel, MatchScore, NonEmptyStr, NormalizedScore


class Candidate(ContractModel):
    job_id: NonEmptyStr
    retrieval_score: NormalizedScore
    keyword_score: NormalizedScore | None = None
    semantic_score: NormalizedScore | None = None
    sources: list[RetrievalChannel] = Field(min_length=1)


class MatchAssessment(ContractModel):
    job_id: NonEmptyStr
    matched: bool
    match_score: MatchScore
    reason: NonEmptyStr
    matched_strengths: list[NonEmptyStr]
    gaps: list[NonEmptyStr]
    evidence: list[NonEmptyStr] = Field(default_factory=list)


class RecommendationItem(ContractModel):
    job: JobFact
    retrieval: Candidate
    assessment: MatchAssessment

    @model_validator(mode="after")
    def require_consistent_matched_job(self) -> RecommendationItem:
        if len({self.job.id, self.retrieval.job_id, self.assessment.job_id}) != 1:
            raise ValueError("job, retrieval, and assessment IDs must match")
        if not self.assessment.matched:
            raise ValueError("recommendation items must contain matched assessments")
        return self


def validate_assessments(
    candidate_job_ids: Sequence[str],
    assessments: Sequence[MatchAssessment],
) -> list[MatchAssessment]:
    """Reject evaluator output that cannot be tied one-to-one to input candidates."""
    allowed = set(candidate_job_ids)
    if len(allowed) != len(candidate_job_ids):
        raise ValueError("candidate job IDs must be unique")

    seen: set[str] = set()
    for assessment in assessments:
        if assessment.job_id not in allowed:
            raise ValueError(f"assessment contains unknown job ID: {assessment.job_id}")
        if assessment.job_id in seen:
            raise ValueError(f"assessment contains duplicate job ID: {assessment.job_id}")
        seen.add(assessment.job_id)
    return list(assessments)
