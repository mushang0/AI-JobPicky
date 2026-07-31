import json
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest

from jobpicky.collection.parsers.guopin import parse

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def test_guopin_parser_reads_public_job_detail() -> None:
    detail_url = "https://www.iguopin.com/job/detail?id=job-guopin-1"

    def request_json(url: str, _headers: object, _payload: object) -> object:
        assert url.endswith("id=job-guopin-1")
        return _fixture("guopin_detail.json")

    jobs = parse(detail_url, request_json)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source_job_id"] == "job-guopin-1"
    assert job["title"] == "测试岗位"
    assert job["locations"] == ["北京"]
    assert job["education_requirement"] == "本科"
    assert job["recruitment_type"] == "校招"
    assert job["salary_min"] == 5000
    assert job["salary_max"] == 7000
    assert job["salary_months"] == 13
    assert isinstance(job["description"], str)
    assert "公开示例工作" in job["description"]


def test_guopin_parser_falls_back_to_lower_company_jobs() -> None:
    company_url = "https://www.iguopin.com/company/jobs?id=company-guopin-1"

    def request_json(url: str, _headers: object, payload: object) -> object:
        if url.endswith("/api/jobs/v1/list"):
            assert isinstance(payload, dict)
            if "company_id_with_sub" in payload:
                return _fixture("guopin_list.json")
            return {"code": 200, "msg": "OK", "data": {"list": [], "total": 0}}
        raise AssertionError(f"unexpected request: {url}")

    jobs = parse(company_url, request_json)

    assert [job["source_job_id"] for job in jobs] == ["job-guopin-1", "job-guopin-2"]
    assert jobs[1]["recruitment_type"] == "实习"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["source_endpoint"] == "jobs/v1/list:company-with-sub"


def test_guopin_parser_reads_custom_site_config_and_public_jobs() -> None:
    site_url = "https://example.iguopin.com/?sessionid="

    def request_json(url: str, _headers: object, payload: object) -> object:
        path = urlsplit(url).path
        if path.endswith("/api/activity/exclusive/v1/info"):
            assert parse_qs(urlsplit(url).query)["domain"] == ["example"]
            return _fixture("guopin_site_config.json")
        if path.endswith("/api/jobs/v1/list"):
            assert isinstance(payload, dict)
            if "company_id_with_sub" in payload:
                return _fixture("guopin_list.json")
            return {"code": 200, "msg": "OK", "data": {"list": [], "total": 0}}
        raise AssertionError(f"unexpected request: {url}")

    jobs = parse(site_url, request_json)

    assert len(jobs) == 2
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["company_id"] == "company-guopin-1"


def test_guopin_parser_reads_jobfair_company_jobs() -> None:
    fair_url = (
        "https://zp.iguopin.com/detail/companyDetail?companyId=company-guopin-1&id=fair-guopin-1"
    )

    def request_json(url: str, _headers: object, payload: object) -> object:
        assert url.endswith("/api/activity/jobfair/company/v1/jobs-list")
        assert payload == {
            "company_id": "company-guopin-1",
            "jobfair_id": "fair-guopin-1",
            "search_type": 2,
            "page": 1,
            "page_size": 10,
        }
        return _fixture("guopin_fair_list.json")

    jobs = parse(fair_url, request_json)

    assert jobs[0]["source_job_id"] == "job-guopin-fair-1"
    assert jobs[0]["detail_url"] == (
        "https://zp.iguopin.com/job/detail?id=job-guopin-fair-1&active=jobfair&active_id=fair-guopin-1"
    )


def test_guopin_parser_does_not_cross_an_access_control_boundary() -> None:
    with pytest.raises(ValueError, match="access-control"):
        parse(
            "https://www.iguopin.com/job/detail?id=private-job",
            lambda _url, _headers, _payload: {
                "code": 10001,
                "msg": "账号类型错误或权限不足",
                "data": None,
            },
        )


def test_guopin_parser_reports_a_verified_empty_public_list() -> None:
    with pytest.raises(ValueError, match="public job list is empty"):
        parse(
            "https://www.iguopin.com/job/list?keyword=empty",
            lambda _url, _headers, _payload: {
                "code": 200,
                "msg": "OK",
                "data": {"list": [], "total": 0},
            },
        )
