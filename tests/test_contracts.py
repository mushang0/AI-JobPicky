from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobpicky.contracts import (
    Candidate,
    CollectedJob,
    CollectionBatch,
    IngestionResult,
    JobFact,
    JobStatus,
    MatchAssessment,
    ProfileSnapshot,
    RecommendationItem,
    RetrievalChannel,
    SearchHit,
    SourceInput,
    validate_assessments,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def collected_job(source_id: str = "source-1") -> CollectedJob:
    return CollectedJob(
        source_id=source_id,
        source_job_id="external-1",
        company_name="Example",
        title="Python Engineer",
        locations=["深圳"],
        description="Build reliable services.",
        detail_url="https://careers.example.com/jobs/1",
        apply_url="https://careers.example.com/jobs/1/apply",
    )


def job_fact(job_id: str = "job-1") -> JobFact:
    return JobFact(
        id=job_id,
        source_id="source-1",
        company_name="Example",
        title="Python Engineer",
        locations=["深圳"],
        description="Build reliable services.",
        detail_url="https://careers.example.com/jobs/1",
        apply_url="https://careers.example.com/jobs/1/apply",
        status=JobStatus.OPEN,
        fact_version="v1",
        first_seen_at=NOW,
        last_confirmed_at=NOW,
        updated_at=NOW,
    )


def candidate(job_id: str = "job-1") -> Candidate:
    return Candidate(
        job_id=job_id,
        retrieval_score=0.82,
        keyword_score=0.75,
        sources=[RetrievalChannel.KEYWORD],
    )


def assessment(job_id: str = "job-1", *, matched: bool = True) -> MatchAssessment:
    return MatchAssessment(
        job_id=job_id,
        matched=matched,
        match_score=88,
        reason="The candidate has relevant backend experience.",
        matched_strengths=["Python"],
        gaps=[],
    )


def test_source_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError):
        SourceInput(company_name="Example", source_url="ftp://example.com/jobs")

    with pytest.raises(ValidationError):
        SourceInput(company_name="Example", source_url="https://user:secret@example.com/jobs")


def test_collection_batch_rejects_jobs_from_another_source() -> None:
    with pytest.raises(ValidationError, match="batch source"):
        CollectionBatch(
            source_id="source-1",
            items=[collected_job("source-2")],
            complete=False,
            method="fixture",
            warnings=["pagination stopped"],
        )


def test_collected_job_cannot_claim_catalog_owned_fields() -> None:
    data = collected_job().model_dump()
    data["status"] = "CLOSED"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CollectedJob.model_validate(data)


def test_incomplete_ingestion_cannot_close_jobs() -> None:
    with pytest.raises(ValidationError, match="closed_count must be zero"):
        IngestionResult(
            job_ids=["job-1"],
            created_count=0,
            updated_count=1,
            unchanged_count=0,
            closed_count=1,
            close_skipped=True,
            complete_accepted=False,
            warnings=["collection was incomplete"],
        )


def test_retrieval_score_is_normalized() -> None:
    with pytest.raises(ValidationError):
        SearchHit(job_id="job-1", score=1.1, channel=RetrievalChannel.SEMANTIC)


def test_recommendation_requires_one_matched_job_id() -> None:
    with pytest.raises(ValidationError, match="IDs must match"):
        RecommendationItem(
            job=job_fact("job-1"),
            retrieval=candidate("job-2"),
            assessment=assessment("job-1"),
        )

    with pytest.raises(ValidationError, match="matched assessments"):
        RecommendationItem(
            job=job_fact(),
            retrieval=candidate(),
            assessment=assessment(matched=False),
        )


def test_evaluator_output_rejects_unknown_and_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="unknown job ID"):
        validate_assessments(["job-1"], [assessment("job-2")])

    with pytest.raises(ValueError, match="duplicate job ID"):
        validate_assessments(["job-1"], [assessment(), assessment()])


def test_profile_snapshot_is_versioned_and_immutable() -> None:
    profile = ProfileSnapshot(
        id="profile-1",
        user_id="user-1",
        version=1,
        created_at=NOW,
        target_locations=["深圳"],
        target_roles=["后端开发"],
        skills=["Python"],
        excluded_roles=[],
        warnings=[],
    )

    with pytest.raises(ValidationError):
        profile.version = 2
