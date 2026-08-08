import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.bilibili import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_bilibili_parser_reads_public_list_and_missing_jd_detail() -> None:
    csrf_response = json.loads((FIXTURES / "bilibili_csrf.json").read_text())
    list_response = json.loads((FIXTURES / "bilibili_list.json").read_text())
    detail_response = json.loads((FIXTURES / "bilibili_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        if endpoint.endswith("/csrf/token"):
            assert method == "GET"
            assert payload is None
            return csrf_response
        if endpoint.endswith("/positionList"):
            assert method == "POST"
            assert payload == {
                "pageSize": 100,
                "pageNum": 1,
                "positionName": "",
                "postCode": None,
                "postCodeList": None,
                "workLocationList": None,
                "workTypeList": [],
                "positionTypeList": [],
                "deptCodeList": None,
                "recruitType": None,
                "practiceTypes": None,
                "onlyHotRecruit": 0,
            }
            return list_response
        assert endpoint.endswith("/position/detail/29759")
        assert method == "GET"
        assert payload is None
        return detail_response

    jobs = parse(
        "https://jobs.bilibili.com/campus/positions?type=3&channel=bilibiliaccounts",
        request,
        max_workers=1,
    )

    assert [job["source_job_id"] for job in jobs] == ["29758", "29759"]
    assert jobs[0]["title"] == "海外招聘实习生"
    assert jobs[0]["description"] == "工作职责：支持招聘工作。\n工作要求：本科及以上。"
    assert jobs[0]["locations"] == ["上海"]
    assert jobs[0]["recruitment_type"] == "实习"
    assert jobs[1]["description"] == "工作职责：负责服务端功能开发。\n工作要求：熟悉 Python 或 Go。"
    assert jobs[1]["detail_url"] == "https://jobs.bilibili.com/campus/positions/29759"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "bilibili-careers"
    assert metadata["list_count"] == 2
    assert metadata["detail_status"] == "list_api"
    detail_metadata = cast(dict[str, object], jobs[1]["metadata"])
    assert detail_metadata["detail_status"] == "public_api"
    assert [call[1] for call in calls] == ["GET", "POST", "GET"]


def test_bilibili_parser_fetches_direct_detail() -> None:
    csrf_response = json.loads((FIXTURES / "bilibili_csrf.json").read_text())
    detail_response = json.loads((FIXTURES / "bilibili_detail.json").read_text())
    calls: list[str] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append(endpoint)
        if endpoint.endswith("/csrf/token"):
            assert method == "GET"
            assert payload is None
            return csrf_response
        assert endpoint.endswith("/position/detail/29759")
        assert method == "GET"
        assert payload is None
        return detail_response

    jobs = parse("https://jobs.bilibili.com/campus/positions/29759", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "29759"
    assert calls == [
        "https://jobs.bilibili.com/api/auth/v1/csrf/token",
        "https://jobs.bilibili.com/api/campus/position/detail/29759",
    ]


def test_bilibili_parser_rejects_missing_csrf_token() -> None:
    def request(_endpoint: str, _method: str, _payload: object) -> object:
        return {"code": 0, "data": None}

    with pytest.raises(ValueError, match="no token"):
        parse("https://jobs.bilibili.com/campus/positions", request, max_workers=1)
