from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from jobpicky.api.dependencies import get_job_pool_service
from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import (
    EducationLevel,
    JobListQuery,
    JobPoolPage,
    RecruitmentType,
)


class RecordingJobPoolService:
    def __init__(self) -> None:
        self.query: JobListQuery | None = None

    async def list_jobs(self, user_id: str | None, query: JobListQuery) -> JobPoolPage:
        del user_id
        self.query = query
        return JobPoolPage(
            items=[],
            total=0,
            page=query.page,
            page_size=query.page_size,
            pool_total=0,
        )


def _app(service: RecordingJobPoolService):
    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_job_pool_service] = lambda: service
    return app


def test_jobs_route_builds_query_from_repeated_query_parameters() -> None:
    service = RecordingJobPoolService()
    with TestClient(_app(service)) as client:
        response = client.get(
            "/api/v1/jobs",
            params=[
                ("page", "2"),
                ("page_size", "20"),
                ("q", "  Python  "),
                ("city", "上海"),
                ("city", "北京"),
                ("city", "北京"),
                ("company_nature", "民企"),
                ("source_id", "source-1"),
                ("source_id", "source-1"),
                ("batch", "秋招提前批"),
                ("recruitment_type", "社招"),
                ("education", "本科"),
                ("graduation_year", "2026"),
                ("graduation_year", "2026"),
                ("salary_min", "10000"),
                ("salary_max", "30000"),
            ],
        )

    assert response.status_code == 200
    assert service.query is not None
    assert service.query.page == 2
    assert service.query.page_size == 20
    assert service.query.q == "Python"
    assert service.query.city == ["上海", "北京"]
    assert service.query.company_nature == ["民营企业"]
    assert service.query.source_id == ["source-1"]
    assert service.query.batch == ["秋招提前批"]
    assert service.query.recruitment_type == [RecruitmentType.SOCIAL]
    assert service.query.education == [EducationLevel.BACHELOR]
    assert service.query.graduation_year == [2026]
    assert service.query.salary_min == 10_000
    assert service.query.salary_max == 30_000


def test_jobs_route_defaults_omitted_filters_to_empty_lists() -> None:
    service = RecordingJobPoolService()
    with TestClient(_app(service)) as client:
        response = client.get("/api/v1/jobs?page=1&page_size=2")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 2,
        "pool_total": 0,
    }
    assert service.query == JobListQuery(page=1, page_size=2)


def test_jobs_route_rejects_query_limits_at_http_boundary() -> None:
    service = RecordingJobPoolService()
    with TestClient(_app(service)) as client:
        too_many_cities = client.get(
            "/api/v1/jobs",
            params=[("city", str(index)) for index in range(51)],
        )
        too_long_q = client.get("/api/v1/jobs", params={"q": "x" * 201})

    for response in (too_many_cities, too_long_q):
        body: dict[str, Any] = response.json()
        assert response.status_code == 422
        assert body["code"] == "VALIDATION_ERROR"
