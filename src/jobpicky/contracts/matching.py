from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field, model_validator

from .catalog import JobFact, RetrievalChannel
from .common import (
    AwareDatetime,
    ContractModel,
    Feedback,
    JobStatus,
    MatchScore,
    NonEmptyStr,
    NormalizedScore,
)


class Candidate(ContractModel):
    job_id: NonEmptyStr
    retrieval_score: NormalizedScore
    keyword_score: NormalizedScore | None = None
    semantic_score: NormalizedScore | None = None
    sources: list[RetrievalChannel] = Field(min_length=1)


class ConstraintStatus(StrEnum):
    SATISFIED = "SATISFIED"
    NOT_SATISFIED = "NOT_SATISFIED"
    UNKNOWN = "UNKNOWN"


class EvidenceAlignment(StrEnum):
    DIRECT = "DIRECT"
    TRANSFERABLE = "TRANSFERABLE"
    PARTIAL = "PARTIAL"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"


class EvidenceImportance(StrEnum):
    CORE = "CORE"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"


class MatchEvidence(ContractModel):
    requirement: NonEmptyStr
    candidate_evidence: NonEmptyStr
    alignment: EvidenceAlignment
    importance: EvidenceImportance
    explanation: NonEmptyStr


class MatchAssessment(ContractModel):
    job_id: NonEmptyStr
    matched: bool
    match_score: MatchScore
    reason: NonEmptyStr
    matched_strengths: list[NonEmptyStr] = Field(default_factory=list)
    gaps: list[NonEmptyStr] = Field(default_factory=list)
    evidence: list[NonEmptyStr] = Field(default_factory=list)
    evidence_details: list[MatchEvidence] = Field(default_factory=list)
    constraint_conclusions: dict[str, ConstraintStatus] = Field(default_factory=dict)


class MatchAssessmentResponse(ContractModel):
    """The only accepted top-level shape returned by an evaluator."""

    assessments: list[MatchAssessment]


# A concise alias for callers that refer to the provider response as an
# evaluation rather than an assessment batch.
EvaluationResponse = MatchAssessmentResponse


class RecommendationCandidate(ContractModel):
    """Pre-evaluation run result: a retrieved job snapshot plus its fusion score."""

    job: JobFact
    retrieval: Candidate

    @model_validator(mode="after")
    def require_consistent_job(self) -> RecommendationCandidate:
        if self.job.id != self.retrieval.job_id:
            raise ValueError("job and retrieval IDs must match")
        return self


class RecommendationItem(ContractModel):
    """Internal persisted result; retrieval is intentionally not a frontend field."""

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


class RecommendationJobView(ContractModel):
    id: NonEmptyStr
    title: NonEmptyStr
    company_name: NonEmptyStr
    company_nature: NonEmptyStr | None = None
    locations: list[NonEmptyStr] = Field(default_factory=list)
    status: JobStatus = JobStatus.UNKNOWN
    published_at: AwareDatetime | None = None
    deadline_at: AwareDatetime | None = None
    first_seen_at: AwareDatetime


class RecommendationAssessmentView(ContractModel):
    """Frontend assessment projection; only summary and capability gaps are public."""

    match_score: MatchScore
    reason: NonEmptyStr
    gaps: list[NonEmptyStr] = Field(default_factory=list)


class RecommendationCardView(ContractModel):
    """Frontend recommendation card, deliberately separate from RecommendationItem."""

    recommendation_id: NonEmptyStr
    run_id: NonEmptyStr
    recommended_at: AwareDatetime
    job: RecommendationJobView
    assessment: RecommendationAssessmentView
    is_saved: bool
    feedback: Feedback | None = None


class RecommendationResultView(RecommendationCardView):
    is_deleted: bool = False
    deleted_at: AwareDatetime | None = None


class RecommendationRunRequest(ContractModel):
    extra_request: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def normalize_extra_request(self) -> RecommendationRunRequest:
        self.extra_request = self.extra_request or None
        return self


class RecommendationFeedbackRequest(ContractModel):
    feedback: Feedback | None


class RecommendationFeedbackView(ContractModel):
    recommendation_id: NonEmptyStr
    feedback: Feedback | None


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
    if len(assessments) != len(candidate_job_ids):
        raise ValueError("assessment job IDs must exactly match candidate job IDs")
    missing = allowed - seen
    if missing:
        raise ValueError(f"assessment contains missing job IDs: {sorted(missing)}")
    return list(assessments)
