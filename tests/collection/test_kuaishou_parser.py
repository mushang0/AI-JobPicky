import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.kuaishou import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_kuaishou_parser_reads_hash_route_list_api() -> None:
    list_response = json.loads((FIXTURES / "kuaishou_list.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/api/v1/open/positions/simple")
        assert method == "POST"
        assert payload == {
            "recruitSubProjectCodes": ["20271779425607"],
            "pageSize": 100,
            "pageNum": 1,
            "positionLabel": "kstar",
        }
        return list_response

    jobs = parse(
        "https://campus.kuaishou.cn/recruit/campus/e/#/campus/jobs?"
        "pageNum=1&positionLabel=kstar&positionNatureCode=fulltime",
        request,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "kuaishou-job-001"
    assert (
        jobs[0]["description"] == "参与招聘平台功能开发。\n熟悉 Python 或 Go，具备良好的工程基础。"
    )
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["detail_url"] == (
        "https://campus.kuaishou.cn/recruit/campus/e/#/campus/job-info/kuaishou-job-001"
    )
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "kuaishou-campus"
    assert metadata["detail_status"] == "list_api"
    assert metadata["list_count"] == 1


def test_kuaishou_parser_fetches_detail_when_list_has_no_description() -> None:
    list_response = {
        "code": 0,
        "result": {
            "total": 1,
            "list": [{"id": "kuaishou-job-001", "name": "平台研发工程师"}],
            "pageNum": 1,
            "pageSize": 100,
            "pages": 1,
        },
    }
    detail_response = json.loads((FIXTURES / "kuaishou_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/simple"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("/find")
        assert method == "GET"
        assert payload == {"id": "kuaishou-job-001"}
        return detail_response

    jobs = parse(
        "https://campus.kuaishou.cn/recruit/campus/e/#/campus/jobs?"
        "recruitSubProjectCodes=20271779425607",
        request,
        max_workers=1,
    )

    assert len(jobs) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "public_api"
    assert jobs[0]["education_requirement"] == "本科及以上"


def test_kuaishou_parser_preserves_array_filters() -> None:
    list_response = json.loads((FIXTURES / "kuaishou_list.json").read_text())

    def request(_endpoint: str, _method: str, payload: object) -> object:
        assert payload == {
            "recruitSubProjectCodes": ["project-a", "project-b"],
            "pageSize": 100,
            "pageNum": 1,
            "positionCategoryCodes": ["J1001", "J1002"],
            "workLocationCodes": ["beijing"],
        }
        return list_response

    jobs = parse(
        "https://campus.kuaishou.cn/recruit/campus/e/#/campus/jobs?"
        "recruitSubProjectCodes=project-a,project-b&positionCategoryCodes=J1001,J1002&"
        "workLocationCodes=beijing",
        request,
    )

    assert len(jobs) == 1


def test_kuaishou_parser_keeps_direct_detail_scoped() -> None:
    detail_response = json.loads((FIXTURES / "kuaishou_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/api/v1/open/positions/find")
        assert method == "GET"
        assert payload == {"id": "kuaishou-job-001"}
        return detail_response

    jobs = parse(
        "https://campus.kuaishou.cn/recruit/campus/e/#/campus/job-info/kuaishou-job-001",
        request,
    )

    assert len(jobs) == 1
    assert calls == [
        (
            "https://campus.kuaishou.cn/recruit/campus/e/api/v1/open/positions/find",
            "GET",
            {"id": "kuaishou-job-001"},
        )
    ]


def test_kuaishou_parser_rejects_missing_description() -> None:
    list_response = {
        "code": 0,
        "result": {
            "total": 1,
            "list": [{"id": "kuaishou-job-001", "name": "平台研发工程师"}],
            "pageNum": 1,
            "pageSize": 100,
            "pages": 1,
        },
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        if endpoint.endswith("/simple"):
            return list_response
        return {"code": 0, "result": {"id": "kuaishou-job-001", "name": "平台研发工程师"}}

    with pytest.raises(ValueError, match="no public description"):
        parse(
            "https://campus.kuaishou.cn/recruit/campus/e/#/campus/jobs",
            request,
            max_workers=1,
        )
