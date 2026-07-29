from __future__ import annotations

from collections.abc import Sequence

from ..contracts import (
    FilterExclusion,
    FilterReasonCode,
    FilterResult,
    HardFilterSpec,
    JobFact,
    JobStatus,
)

# Ordinal education levels for hard-filter comparison (plan 003, decision 3).
# A job excludes the candidate only when its requirement level is strictly
# higher than the candidate's level; anything unparseable passes (R2).
_EDUCATION_LEVELS = {
    "专科": 1,
    "大专": 1,
    "本科": 2,
    "学士": 2,
    "硕士": 3,
    "研究生": 3,
    "博士": 4,
}


def _education_level(text: str | None) -> int | None:
    if not text:
        return None
    # Take the highest matched level: "博士研究生" contains both "研究生"
    # and "博士", and the doctorate is what the text actually means.
    levels = [level for keyword, level in _EDUCATION_LEVELS.items() if keyword in text]
    return max(levels, default=None)


def evaluate_job(spec: HardFilterSpec, job: JobFact) -> FilterExclusion | None:
    """Return the first exclusion reason for a job, or None when it passes.

    Dimensions are checked in FilterReasonCode definition order. Missing job
    facts never cause an exclusion: insufficient information must not become
    an exclusion condition (R2).
    """
    if spec.only_open and job.status != JobStatus.OPEN:
        return _exclusion(
            job,
            FilterReasonCode.JOB_NOT_OPEN,
            f"岗位状态为 {job.status}，当前不在开放招聘中",
        )

    if (
        spec.target_locations
        and job.locations
        and not set(spec.target_locations) & set(job.locations)
    ):
        return _exclusion(
            job,
            FilterReasonCode.LOCATION_MISMATCH,
            f"岗位地点 {job.locations} 与目标地点 {spec.target_locations} 无交集",
        )

    if (
        spec.recruitment_types
        and job.recruitment_type is not None
        and job.recruitment_type not in spec.recruitment_types
    ):
        return _exclusion(
            job,
            FilterReasonCode.RECRUITMENT_TYPE_MISMATCH,
            f"招聘类型 {job.recruitment_type} 不在目标类型 {spec.recruitment_types} 内",
        )

    candidate_level = _education_level(spec.education)
    required_level = _education_level(job.education_requirement)
    if (
        candidate_level is not None
        and required_level is not None
        and required_level > candidate_level
    ):
        return _exclusion(
            job,
            FilterReasonCode.EDUCATION_MISMATCH,
            f"岗位要求学历 {job.education_requirement} 高于求职者学历 {spec.education}",
        )

    title = job.title.lower()
    for role in spec.excluded_roles:
        if role.lower() in title:
            return _exclusion(
                job,
                FilterReasonCode.EXCLUDED_ROLE,
                f"岗位名称包含排除方向 {role}",
            )

    if (
        spec.graduation_year is not None
        and job.graduation_years
        and spec.graduation_year not in job.graduation_years
    ):
        return _exclusion(
            job,
            FilterReasonCode.GRADUATION_YEAR_MISMATCH,
            f"岗位面向毕业年份 {job.graduation_years} 不含 {spec.graduation_year}",
        )

    if (
        spec.min_salary is not None
        and job.salary_max is not None
        and job.salary_max < spec.min_salary
    ):
        return _exclusion(
            job,
            FilterReasonCode.SALARY_MISMATCH,
            f"岗位薪资上限 {job.salary_max} 低于期望下限 {spec.min_salary}",
        )

    return None


def apply_filter(spec: HardFilterSpec, jobs: Sequence[JobFact]) -> FilterResult:
    """Partition jobs into eligible IDs and exclusions per the spec."""
    eligible: list[str] = []
    excluded: list[FilterExclusion] = []
    for job in jobs:
        exclusion = evaluate_job(spec, job)
        if exclusion is None:
            eligible.append(job.id)
        else:
            excluded.append(exclusion)
    return FilterResult(eligible_job_ids=eligible, excluded=excluded)


def _exclusion(
    job: JobFact,
    reason_code: FilterReasonCode,
    reason: str,
) -> FilterExclusion:
    return FilterExclusion(job_id=job.id, reason_code=str(reason_code), reason=reason)


__all__ = ["apply_filter", "evaluate_job"]
