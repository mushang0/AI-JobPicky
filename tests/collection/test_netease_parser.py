import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.netease import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_netease_parser_reads_public_project_api() -> None:
    list_response = json.loads((FIXTURES / "netease_list.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/position/getJobList")
        assert method == "GET"
        assert payload == {"projectId": "102", "pageSize": 100, "currentPage": 1}
        return list_response

    jobs = parse("https://campus.game.163.com/app/job/position?id=102", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "2001"
    assert jobs[0]["description"] == "参与客户端功能开发。\n熟悉一种主流编程语言。"
    assert jobs[0]["detail_url"] == (
        "https://campus.game.163.com/app/detail/index?id=2001&projectId=102"
    )
    assert len(calls) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "netease-campus"
    assert metadata["detail_status"] == "list_api"


def test_netease_parser_rejects_missing_project_id() -> None:
    with pytest.raises(ValueError, match="no numeric project id"):
        parse("https://campus.game.163.com/app/job/position")


def test_netease_hr_parser_reads_public_direct_detail() -> None:
    detail_response = json.loads((FIXTURES / "netease_hr_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/api/hr163/position/query")
        assert method == "GET"
        assert payload == {"id": "3001"}
        return detail_response

    jobs = parse("https://hr.163.com/job-detail.html?id=3001&lang=zh", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "3001"
    assert jobs[0]["locations"] == ["杭州", "上海"]
    assert jobs[0]["education_requirement"] == "本科"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "netease-hr"
