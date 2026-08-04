import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.baidu import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_baidu_parser_reads_public_list_api() -> None:
    list_response = json.loads((FIXTURES / "baidu_list.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/httservice/getPostListNew")
        assert method == "POST"
        assert payload == {
            "recruitType": "GRADUATE",
            "workPlace": [],
            "pageSize": 10,
            "keyWord": "",
            "postType": [],
            "curPage": 1,
            "projectType": "",
        }
        return list_response

    jobs = parse("https://talent.baidu.com/jobs/list?recruitType=GRADUATE", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "baidu-job-001"
    assert jobs[0]["description"] == "参与平台功能开发。\n具备良好的工程基础。"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["detail_url"] == ("https://talent.baidu.com/jobs/detail/GRADUATE/baidu-job-001")
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "baidu-campus"
    assert metadata["detail_status"] == "list_api"
    assert metadata["list_count"] == 1


def test_baidu_parser_fetches_detail_when_list_has_no_description() -> None:
    list_response = {
        "status": "ok",
        "data": {
            "pageNum": 1,
            "pageSize": 10,
            "total": "1",
            "list": [{"postId": "baidu-job-001", "name": "平台研发工程师"}],
        },
    }
    detail_response = json.loads((FIXTURES / "baidu_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("getPostListNew"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("getPostDetail")
        assert method == "GET"
        assert payload == {"postId": "baidu-job-001", "recruitType": "GRADUATE"}
        return detail_response

    jobs = parse("https://talent.baidu.com/jobs/list", request, max_workers=1)

    assert len(jobs) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "public_api"


def test_baidu_parser_keeps_query_filters() -> None:
    list_response = json.loads((FIXTURES / "baidu_list.json").read_text())

    def request(_endpoint: str, _method: str, payload: object) -> object:
        assert payload == {
            "recruitType": "GRADUATE",
            "workPlace": [],
            "pageSize": 10,
            "keyWord": "AI",
            "postType": [],
            "curPage": 1,
            "projectType": "3",
        }
        return list_response

    jobs = parse(
        "https://talent.baidu.com/jobs/list?recruitType=GRADUATE&projectType=3&search=AI",
        request,
    )

    assert len(jobs) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["project_type"] == "3"


def test_baidu_parser_keeps_direct_detail_scoped() -> None:
    detail_response = json.loads((FIXTURES / "baidu_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("getPostDetail")
        assert method == "GET"
        assert payload == {"postId": "baidu-job-001", "recruitType": "GRADUATE"}
        return detail_response

    jobs = parse(
        "https://talent.baidu.com/jobs/detail/GRADUATE/baidu-job-001?share=1",
        request,
    )

    assert len(jobs) == 1
    assert calls == [
        (
            "https://talent.baidu.com/httservice/getPostDetail",
            "GET",
            {"postId": "baidu-job-001", "recruitType": "GRADUATE"},
        )
    ]


def test_baidu_parser_rejects_missing_description() -> None:
    list_response = {
        "status": "ok",
        "data": {
            "pageNum": 1,
            "pageSize": 10,
            "total": "1",
            "list": [{"postId": "baidu-job-001", "name": "平台研发工程师"}],
        },
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        if endpoint.endswith("getPostListNew"):
            return list_response
        return {"status": "ok", "data": {"postId": "baidu-job-001", "name": "平台研发工程师"}}

    with pytest.raises(ValueError, match="no public description"):
        parse("https://talent.baidu.com/jobs/list", request, max_workers=1)
