from __future__ import annotations

from jobpicky.catalog import apply_filter, evaluate_job
from jobpicky.contracts import FilterReasonCode, JobStatus

from .factories import make_job, make_spec


def test_matching_job_is_eligible() -> None:
    assert evaluate_job(make_spec(), make_job()) is None


def test_closed_job_is_excluded_when_only_open() -> None:
    exclusion = evaluate_job(make_spec(), make_job(status=JobStatus.CLOSED))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.JOB_NOT_OPEN


def test_unknown_status_is_excluded_when_only_open() -> None:
    exclusion = evaluate_job(make_spec(), make_job(status=JobStatus.UNKNOWN))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.JOB_NOT_OPEN


def test_closed_job_passes_when_only_open_disabled() -> None:
    spec = make_spec(only_open=False)
    assert evaluate_job(spec, make_job(status=JobStatus.CLOSED)) is None


def test_location_mismatch_is_excluded() -> None:
    spec = make_spec(target_locations=["北京"])
    exclusion = evaluate_job(spec, make_job(locations=["上海"]))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.LOCATION_MISMATCH


def test_location_overlap_passes() -> None:
    spec = make_spec(target_locations=["北京", "上海"])
    assert evaluate_job(spec, make_job(locations=["上海", "深圳"])) is None


def test_empty_job_locations_pass() -> None:
    # R2: missing job facts must not become an exclusion condition.
    spec = make_spec(target_locations=["北京"])
    assert evaluate_job(spec, make_job(locations=[])) is None


def test_recruitment_type_mismatch_is_excluded() -> None:
    spec = make_spec(recruitment_types=["社会招聘"])
    exclusion = evaluate_job(spec, make_job(recruitment_type="校园招聘"))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.RECRUITMENT_TYPE_MISMATCH


def test_unknown_recruitment_type_passes() -> None:
    spec = make_spec(recruitment_types=["社会招聘"])
    assert evaluate_job(spec, make_job(recruitment_type=None)) is None


def test_higher_education_requirement_is_excluded() -> None:
    spec = make_spec(education="本科")
    exclusion = evaluate_job(spec, make_job(education_requirement="硕士及以上"))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.EDUCATION_MISMATCH


def test_lower_or_equal_education_requirement_passes() -> None:
    spec = make_spec(education="硕士")
    assert evaluate_job(spec, make_job(education_requirement="本科及以上")) is None


def test_doctoral_graduate_student_reads_as_doctorate() -> None:
    # "博士研究生" contains "研究生" but means the doctorate level.
    master_spec = make_spec(education="硕士")
    exclusion = evaluate_job(master_spec, make_job(education_requirement="博士研究生"))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.EDUCATION_MISMATCH

    doctoral_spec = make_spec(education="博士研究生")
    assert evaluate_job(doctoral_spec, make_job(education_requirement="博士")) is None


def test_unparseable_education_requirement_passes() -> None:
    spec = make_spec(education="本科")
    assert evaluate_job(spec, make_job(education_requirement="学历不限")) is None
    assert evaluate_job(spec, make_job(education_requirement=None)) is None


def test_unparseable_profile_education_passes() -> None:
    spec = make_spec(education="其他")
    assert evaluate_job(spec, make_job(education_requirement="博士")) is None


def test_excluded_role_in_title_is_excluded() -> None:
    spec = make_spec(excluded_roles=["销售"])
    exclusion = evaluate_job(spec, make_job(title="大客户销售经理"))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.EXCLUDED_ROLE


def test_excluded_role_matching_is_case_insensitive() -> None:
    spec = make_spec(excluded_roles=["java"])
    exclusion = evaluate_job(spec, make_job(title="Java 开发工程师"))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.EXCLUDED_ROLE


def test_graduation_year_mismatch_is_excluded() -> None:
    spec = make_spec(graduation_year=2026)
    exclusion = evaluate_job(spec, make_job(graduation_years=[2027]))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.GRADUATION_YEAR_MISMATCH


def test_empty_graduation_years_pass() -> None:
    spec = make_spec(graduation_year=2026)
    assert evaluate_job(spec, make_job(graduation_years=[])) is None


def test_salary_below_expectation_is_excluded() -> None:
    spec = make_spec(min_salary=30000)
    exclusion = evaluate_job(spec, make_job(salary_max=25000))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.SALARY_MISMATCH


def test_salary_meeting_expectation_passes() -> None:
    spec = make_spec(min_salary=20000)
    assert evaluate_job(spec, make_job(salary_max=25000)) is None


def test_unknown_salary_passes() -> None:
    spec = make_spec(min_salary=30000)
    assert evaluate_job(spec, make_job(salary_max=None)) is None


def test_first_reason_wins_in_definition_order() -> None:
    spec = make_spec(target_locations=["北京"], min_salary=99999)
    exclusion = evaluate_job(spec, make_job(status=JobStatus.CLOSED))
    assert exclusion is not None
    assert exclusion.reason_code == FilterReasonCode.JOB_NOT_OPEN


def test_apply_filter_partitions_jobs() -> None:
    spec = make_spec(target_locations=["上海"])
    eligible = make_job(id="job-1", locations=["上海"])
    wrong_city = make_job(id="job-2", locations=["北京"])
    closed = make_job(id="job-3", status=JobStatus.CLOSED)

    result = apply_filter(spec, [eligible, wrong_city, closed])

    assert result.eligible_job_ids == ["job-1"]
    assert {item.job_id: item.reason_code for item in result.excluded} == {
        "job-2": FilterReasonCode.LOCATION_MISMATCH,
        "job-3": FilterReasonCode.JOB_NOT_OPEN,
    }
