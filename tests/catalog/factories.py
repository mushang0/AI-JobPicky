from __future__ import annotations

from datetime import UTC, datetime

from jobpicky.contracts import HardFilterSpec, JobFact, JobStatus


def make_job(**overrides: object) -> JobFact:
    defaults: dict[str, object] = {
        "id": "job-1",
        "source_id": "source-1",
        "company_name": "示例科技",
        "company_nature": "民营",
        "title": "后端工程师",
        "locations": ["上海"],
        "description": "负责 Python 后端服务开发，使用 PostgreSQL。",
        "detail_url": "https://jobs.example.com/jobs/1",
        "apply_url": "https://jobs.example.com/jobs/1/apply",
        "recruitment_type": "校园招聘",
        "education_requirement": "本科及以上",
        "salary_min": 15000,
        "salary_max": 25000,
        "salary_months": 14,
        "graduation_years": [2027],
        "status": JobStatus.OPEN,
        "fact_version": "v1",
        "published_at": None,
        "deadline_at": None,
        "first_seen_at": datetime(2026, 1, 1, tzinfo=UTC),
        "last_confirmed_at": datetime(2026, 1, 2, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return JobFact(**defaults)  # type: ignore[arg-type]


def make_spec(**overrides: object) -> HardFilterSpec:
    defaults: dict[str, object] = {
        "target_locations": [],
        "excluded_roles": [],
        "education": None,
        "recruitment_types": [],
        "graduation_year": None,
        "min_salary": None,
        "only_open": True,
    }
    defaults.update(overrides)
    return HardFilterSpec(**defaults)  # type: ignore[arg-type]
