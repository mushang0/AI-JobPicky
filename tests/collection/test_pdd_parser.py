import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.pdd import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_pdd_parser_reads_public_list_and_detail_api() -> None:
    list_response = json.loads((FIXTURES / "pdd_list.json").read_text())
    detail_response = json.loads((FIXTURES / "pdd_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/position/list"):
            assert method == "POST"
            assert payload == {"page": 1, "pageSize": 10}
            return list_response
        assert endpoint.endswith("/position/detail")
        assert method == "POST"
        assert payload == {"id": "pdd-job-001"}
        return detail_response

    jobs = parse("https://careers.pddglobalhr.com/campus/grad", request, max_workers=1)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "pdd-job-001"
    assert jobs[0]["description"] == "参与平台服务开发。\n具备良好的工程基础。"
    assert jobs[0]["locations"] == ["上海"]
    assert jobs[0]["detail_url"] == (
        "https://careers.pddglobalhr.com/campus/grad/detail?positionId=pdd-job-001"
    )
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "pdd-global-hr"
    assert metadata["list_count"] == 1


def test_pdd_parser_rejects_missing_description() -> None:
    list_response = {
        "success": True,
        "result": {"total": "1", "list": [{"id": "pdd-job-001", "name": "平台研发工程师"}]},
    }
    detail_response = {"success": True, "result": {"id": "pdd-job-001"}}

    def request(endpoint: str, _method: str, _payload: object) -> object:
        return list_response if endpoint.endswith("/position/list") else detail_response

    with pytest.raises(ValueError, match="no public description"):
        parse("https://careers.pddglobalhr.com/campus/grad", request, max_workers=1)


def test_pdd_parser_keeps_a_direct_position_link_scoped() -> None:
    detail_response = json.loads((FIXTURES / "pdd_detail.json").read_text())
    calls: list[str] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append(endpoint)
        assert endpoint.endswith("/position/detail")
        assert method == "POST"
        assert payload == {"id": "pdd-job-001"}
        return detail_response

    jobs = parse(
        "https://careers.pddglobalhr.com/campus/grad/detail?positionId=pdd-job-001",
        request,
        max_workers=1,
    )

    assert len(jobs) == 1
    assert calls == ["https://careers.pddglobalhr.com/api/careers/api/recruit/position/detail"]


def test_pdd_parser_preserves_public_list_filters() -> None:
    list_response = json.loads((FIXTURES / "pdd_list.json").read_text())
    detail_response = json.loads((FIXTURES / "pdd_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/position/list"):
            assert method == "POST"
            assert payload == {
                "page": 1,
                "pageSize": 10,
                "recruitTypeList": ["technical_session"],
            }
            return list_response
        return detail_response

    jobs = parse(
        "https://careers.pddglobalhr.com/campus/m/pages/index/index?"
        "type=fullTime&recruitType=technical_session&jobList=&workLocationList=",
        request,
        max_workers=1,
    )

    assert len(jobs) == 1
