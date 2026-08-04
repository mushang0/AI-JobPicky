from datetime import UTC, datetime

import pytest
from catalog.factories import make_job
from pydantic import ValidationError

from jobpicky.contracts import (
    AuthUserView,
    Candidate,
    CreditSummary,
    CreditUsage,
    CurrentProfileView,
    EducationLevel,
    ErrorCode,
    Feedback,
    FilterOptionsView,
    JobDetailView,
    JobFilterSource,
    JobListItem,
    JobListQuery,
    JobSourceView,
    JobStatus,
    LoginRequest,
    MatchAssessment,
    ProfileDraft,
    ProfileImportDraft,
    ProfileImportView,
    ProfileSaveRequest,
    RecommendationAssessmentView,
    RecommendationCardView,
    RecommendationItem,
    RecommendationJobView,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunRequest,
    RecommendationStep,
    RecommendationTaskStatus,
    RecommendationTaskView,
    RecruitmentType,
    RetrievalChannel,
    UserRole,
    error_message,
)

NOW = datetime(2026, 7, 31, tzinfo=UTC)


def list_item() -> JobListItem:
    return JobListItem(
        id="job-1",
        title="Python 后端工程师",
        company_name="示例科技",
        company_nature="民营企业",
        locations=["上海"],
        source=JobSourceView(id="source-1", name="Moka"),
        batch="秋招提前批",
        recruitment_type=RecruitmentType.SOCIAL,
        education_requirement="本科",
        salary_min=15_000,
        salary_max=25_000,
        description_preview="负责 Python 后端服务开发",
        last_confirmed_at=NOW,
    )


def test_job_list_and_detail_views_do_not_expose_internal_fact_fields() -> None:
    item = list_item()
    assert item.is_saved is None
    assert "fact_version" not in item.model_dump()

    detail = JobDetailView(
        id=item.id,
        title=item.title,
        company_name=item.company_name,
        company_nature=item.company_nature,
        locations=item.locations,
        source=item.source,
        batch=item.batch,
        recruitment_type=item.recruitment_type,
        education_requirement=item.education_requirement,
        graduation_years=item.graduation_years,
        salary_min=item.salary_min,
        salary_max=item.salary_max,
        salary_months=item.salary_months,
        description="负责 Python 后端服务开发。",
        detail_url="https://example.com/jobs/1",
        apply_url="https://example.com/jobs/1/apply",
        status=JobStatus.OPEN,
        published_at=NOW,
        first_seen_at=NOW,
        last_confirmed_at=NOW,
        updated_at=NOW,
    )
    assert "description_preview" not in detail.model_dump()
    assert detail.is_saved is None
    with pytest.raises(ValidationError):
        JobListItem(**item.model_dump(), fact_version="v1")  # type: ignore[call-arg]


def test_job_list_query_normalizes_repeated_filters_and_checks_salary_range() -> None:
    query = JobListQuery(
        q="  Python ",
        city=[" 上海 ", "上海"],
        recruitment_type=[RecruitmentType.SOCIAL, RecruitmentType.SOCIAL],
        education=[EducationLevel.BACHELOR],
        salary_min=20_000,
        salary_max=30_000,
    )
    assert query.q == "Python"
    assert query.city == ["上海"]
    assert query.recruitment_type == [RecruitmentType.SOCIAL]

    with pytest.raises(ValidationError):
        JobListQuery(salary_min=30_000, salary_max=20_000)


def test_filter_options_use_explicit_limits_and_normalized_values() -> None:
    options = FilterOptionsView(
        cities=["北京", "上海"],
        company_natures=["民营企业"],
        sources=[JobFilterSource(platform="Moka", source_ids=["source-1"])],
        batches=["秋招提前批"],
        recruitment_types=list(RecruitmentType),
        educations=list(EducationLevel),
        graduation_years=[2026, 2027],
        limits={  # type: ignore[arg-type]
            "default_page_size": 30,
            "public_page_size_max": 30,
            "authenticated_page_size_max": 100,
        },
    )
    assert options.limits.default_page_size == 30


def test_profile_input_is_user_editable_but_snapshot_and_view_keep_server_fields() -> None:
    draft = ProfileSaveRequest(
        base_version=None,
        target_roles=[" 后端工程师 ", "后端工程师"],
        target_locations=[],
        recruitment_types=[RecruitmentType.SOCIAL],
        skills=["Python"],
        excluded_roles=[],
        education=EducationLevel.BACHELOR,
        expected_salary_min=20_000,
        extra_request=" 远程优先 ",
    )
    assert draft.target_roles == ["后端工程师"]
    assert draft.recruitment_types == [RecruitmentType.SOCIAL]
    assert draft.extra_request == "远程优先"
    with pytest.raises(ValidationError):
        ProfileDraft(**draft.model_dump(), warnings=[])  # type: ignore[call-arg]

    view = CurrentProfileView(
        id="profile-1",
        version=1,
        target_roles=draft.target_roles,
        target_locations=[],
        recruitment_types=draft.recruitment_types,
        skills=draft.skills,
        education=EducationLevel.BACHELOR,
        excluded_roles=[],
        warnings=[],
        created_at=NOW,
    )
    assert "user_id" not in view.model_dump()


def test_profile_required_fields_and_limits_are_checked() -> None:
    with pytest.raises(ValidationError):
        ProfileSaveRequest(target_roles=[], skills=[], experience_summary=None)
    with pytest.raises(ValidationError):
        ProfileSaveRequest(
            target_roles=["后端工程师"],
            skills=[],
            experience_summary=None,
        )
    with pytest.raises(ValidationError):
        ProfileSaveRequest(
            target_roles=["后端工程师"],
            skills=["Python"],
            expected_salary_min=1_000_001,
        )

    imported = ProfileImportView(draft=ProfileImportDraft(), warnings=["请补充目标岗位。"])
    assert imported.draft.target_roles == []


def test_recommendation_card_does_not_reuse_internal_retrieval_dto() -> None:
    internal = RecommendationItem(
        job=make_job(),
        retrieval=Candidate(
            job_id="job-1",
            retrieval_score=0.8,
            sources=[RetrievalChannel.KEYWORD],
        ),
        assessment=MatchAssessment(
            job_id="job-1",
            matched=True,
            match_score=88,
            reason="有相关后端经验。",
            matched_strengths=["Python"],
            gaps=[],
        ),
    )
    assert "retrieval" in internal.model_dump()

    card = RecommendationCardView(
        recommendation_id="rec-1",
        run_id="run-1",
        recommended_at=NOW,
        job=RecommendationJobView(
            id="job-1",
            title="后端工程师",
            company_name="示例科技",
            locations=["上海"],
            first_seen_at=NOW,
        ),
        assessment=RecommendationAssessmentView(
            match_score=internal.assessment.match_score,
            reason=internal.assessment.reason,
            matched_strengths=internal.assessment.matched_strengths,
            gaps=internal.assessment.gaps,
            evidence=internal.assessment.evidence,
        ),
        is_saved=True,
        feedback=Feedback.LIKE,
    )
    assert "retrieval" not in card.model_dump()
    assert "job_id" not in card.assessment.model_dump()
    with pytest.raises(ValidationError):
        RecommendationCardView(**card.model_dump(), retrieval={})  # type: ignore[call-arg]

    result = RecommendationResultView(**card.model_dump(), is_deleted=True, deleted_at=NOW)
    assert result.is_deleted


def test_recommendation_task_exposes_real_progress_and_credit_usage() -> None:
    task = RecommendationTaskView(
        run_id="run-1",
        status=RecommendationTaskStatus.RUNNING,
        current_step=RecommendationStep.EVALUATE,
        progress_percent=65,
        created_at=NOW,
        credits=CreditUsage(cost=100, refunded=False, net_spent=100),
    )
    assert task.progress_percent == 65
    assert CreditSummary(balance=9900, recommendation_cost=100).balance == 9900
    with pytest.raises(ValidationError):
        CreditUsage(cost=100, refunded=True, net_spent=100)
    assert RecommendationRunRequest(extra_request="  ").extra_request is None
    accepted = RecommendationRunAccepted(
        run_id="run-1",
        status=RecommendationTaskStatus.PENDING,
        credits_charged=100,
        balance_after=9900,
    )
    assert accepted.status is RecommendationTaskStatus.PENDING


def test_auth_user_and_password_contracts_are_safe() -> None:
    user = AuthUserView(
        id="user-1",
        email=" User@Example.com ",
        role=UserRole.USER,
        created_at=NOW,
    )
    assert user.email == "user@example.com"
    request = LoginRequest(email="user@example.com", password=" 12345678901 ")
    assert request.password.startswith(" ") and request.password.endswith(" ")
    for password in ("123456", "123456789012345"):
        LoginRequest(email="user@example.com", password=password)
    for password in ("12345", "1234567890123456"):
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password=password)
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="123456")


def test_error_codes_have_chinese_default_messages() -> None:
    assert ErrorCode.AUTHENTICATION_REQUIRED.value in {item.value for item in ErrorCode}
    assert error_message(ErrorCode.INVALID_CREDENTIALS) == "邮箱或密码错误。"
    assert error_message(ErrorCode.INSUFFICIENT_CREDITS) == "积分余额不足，请先补充积分。"
