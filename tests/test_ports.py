from inspect import signature

from jobpicky.ports import (
    AdminJobQueryPort,
    AdminRecommendationRunQueryPort,
    CrawlOrchestratorPort,
    MatchingPort,
    ProfileSnapshotReaderPort,
    RecommendationOrchestratorPort,
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


def test_crawl_history_is_paginated_and_admin_scoped() -> None:
    assert parameter_names(CrawlOrchestratorPort, "list_runs") == [
        "self",
        "admin_id",
        "page",
        "page_size",
    ]


def test_admin_recommendation_queries_have_independent_authorization_port() -> None:
    assert AdminRecommendationRunQueryPort is not RecommendationOrchestratorPort
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


def test_matching_port_owns_planning_and_candidate_fusion() -> None:
    assert {
        "build_filter_spec",
        "build_query_text",
        "merge_candidates",
    }.issubset(set(dir(MatchingPort)))
