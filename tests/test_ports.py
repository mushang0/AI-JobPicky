from inspect import signature
from typing import get_type_hints

from jobpicky.contracts import (
    Page,
    RecommendationResultView,
    RecommendationTaskView,
)
from jobpicky.ports import (
    AdminJobQueryPort,
    AdminRecommendationRunQueryPort,
    AuthenticationPort,
    CrawlOrchestratorPort,
    CreditsPort,
    JobPoolQueryPort,
    MatchingPort,
    ProfileApplicationPort,
    ProfileSnapshotReaderPort,
    RecommendationOrchestratorPort,
    RecommendationQueryPort,
    SavedJobPort,
    UserJobQueryPort,
)


def parameter_names(port: type, method: str) -> list[str]:
    return list(signature(getattr(port, method)).parameters)


def test_user_run_queries_are_paginated_and_user_scoped() -> None:
    assert parameter_names(RecommendationOrchestratorPort, "list_runs") == [
        "self",
        "user_id",
        "page",
        "page_size",
    ]
    assert parameter_names(RecommendationOrchestratorPort, "get_run") == [
        "self",
        "user_id",
        "run_id",
    ]


def test_get_results_returns_final_recommendation_items() -> None:
    hints = get_type_hints(RecommendationOrchestratorPort.get_results)
    assert hints["return"] == Page[RecommendationResultView]


def test_recommendation_start_uses_the_current_profile_from_user_context() -> None:
    assert parameter_names(RecommendationOrchestratorPort, "start") == [
        "self",
        "user_id",
        "extra_request",
        "idempotency_key",
    ]
    assert (
        get_type_hints(RecommendationOrchestratorPort.list_runs)["return"]
        == Page[RecommendationTaskView]
    )


def test_crawl_history_is_paginated_and_admin_scoped() -> None:
    assert parameter_names(CrawlOrchestratorPort, "list_runs") == [
        "self",
        "admin_id",
        "page",
        "page_size",
    ]


def test_admin_recommendation_queries_have_independent_authorization_port() -> None:
    assert id(AdminRecommendationRunQueryPort) != id(RecommendationOrchestratorPort)
    assert parameter_names(AdminRecommendationRunQueryPort, "list_runs") == [
        "self",
        "admin_id",
        "page",
        "page_size",
    ]
    assert parameter_names(AdminRecommendationRunQueryPort, "get_run") == [
        "self",
        "admin_id",
        "run_id",
    ]


def test_profile_snapshot_reader_and_admin_job_query_keep_context_at_boundary() -> None:
    assert parameter_names(ProfileSnapshotReaderPort, "get_snapshot") == [
        "self",
        "user_id",
        "profile_id",
    ]
    assert parameter_names(AdminJobQueryPort, "get_job") == [
        "self",
        "admin_id",
        "job_id",
    ]
    assert parameter_names(UserJobQueryPort, "get_job") == [
        "self",
        "user_id",
        "job_id",
    ]
    assert parameter_names(AdminJobQueryPort, "list_jobs") == [
        "self",
        "admin_id",
        "query",
        "page",
        "page_size",
    ]


def test_new_user_ports_keep_identity_and_resource_ownership_at_the_boundary() -> None:
    assert parameter_names(ProfileApplicationPort, "save_current") == [
        "self",
        "user_id",
        "draft",
        "idempotency_key",
    ]
    assert parameter_names(ProfileApplicationPort, "import_resume") == [
        "self",
        "user_id",
        "filename",
        "content_type",
        "content",
    ]
    assert parameter_names(AuthenticationPort, "get_current_user") == [
        "self",
        "user_id",
    ]
    assert parameter_names(CreditsPort, "get_summary") == ["self", "user_id"]
    assert parameter_names(SavedJobPort, "set_saved") == [
        "self",
        "user_id",
        "job_id",
        "is_saved",
    ]
    assert parameter_names(JobPoolQueryPort, "list_jobs") == [
        "self",
        "user_id",
        "query",
    ]
    assert parameter_names(RecommendationQueryPort, "update_feedback") == [
        "self",
        "user_id",
        "recommendation_id",
        "feedback",
    ]


def test_matching_port_owns_planning_and_candidate_fusion() -> None:
    assert {
        "build_filter_spec",
        "build_query_text",
        "merge_candidates",
    }.issubset(set(dir(MatchingPort)))
