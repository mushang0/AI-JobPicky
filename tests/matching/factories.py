from __future__ import annotations

from datetime import UTC, datetime

from jobpicky.contracts import ProfileSnapshot, RetrievalChannel, SearchHit


def make_profile(**overrides: object) -> ProfileSnapshot:
    defaults: dict[str, object] = {
        "id": "profile-1",
        "user_id": "user-1",
        "version": 1,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "target_locations": ["上海"],
        "target_roles": ["后端工程师"],
        "skills": ["Python", "PostgreSQL"],
        "excluded_roles": [],
        "education": "本科",
        "graduation_year": 2027,
        "expected_salary_min": 20000,
        "experience_summary": "三年后端开发经验",
        "extra_request": None,
        "warnings": [],
    }
    defaults.update(overrides)
    return ProfileSnapshot(**defaults)  # type: ignore[arg-type]


def make_hit(
    job_id: str,
    score: float,
    channel: RetrievalChannel = RetrievalChannel.KEYWORD,
) -> SearchHit:
    return SearchHit(job_id=job_id, score=score, channel=channel)
