import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.oppo import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_oppo_parser_reads_public_campus_list() -> None:
    response = json.loads((FIXTURES / "oppo_list.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/openapi/position/pageNew")
        assert method == "POST"
        assert payload == {
            "pageNum": 1,
            "pageSize": 10,
            "positionName": "",
            "projectList": [],
            "positionTypeList": ["Software"],
            "workCityCodeList": ["440300"],
        }
        return response

    jobs = parse(
        "https://careers.oppo.com/university/oppo/campus/post?"
        "positionType=Software&workCityCode=440300",
        request,
        max_workers=1,
    )

    assert len(jobs) == 2
    assert jobs[0]["source_job_id"] == "1870"
    assert jobs[0]["title"] == "平台研发工程师"
    assert jobs[0]["description"] == "负责平台服务研发与性能优化。\n计算机相关专业，本科及以上。"
    assert jobs[0]["locations"] == ["深圳市", "成都市"]
    assert jobs[0]["recruitment_type"] == "校招"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "oppo-careers"
    assert metadata["detail_status"] == "list_api"
    assert metadata["list_count"] == 2


def test_oppo_parser_fetches_direct_detail() -> None:
    response = json.loads((FIXTURES / "oppo_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/openapi/position/detail")
        assert method == "GET"
        assert payload == {"id": "1870"}
        return response

    jobs = parse("https://careers.oppo.com/campus/post/1870", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "1870"
    assert jobs[0]["detail_url"] == "https://careers.oppo.com/campus/post/1870"
    assert jobs[0]["locations"] == ["深圳市"]
    assert calls == [
        (
            "https://careers.oppo.com/openapi/position/detail",
            "GET",
            {"id": "1870"},
        )
    ]


def test_oppo_parser_fetches_detail_when_list_has_no_jd() -> None:
    list_response = {
        "code": 0,
        "data": {
            "records": [{"idRecruitPosition": 1870, "positionName": "平台研发工程师"}],
            "total": 1,
            "pages": 1,
        },
        "msg": "success",
    }
    detail_response = json.loads((FIXTURES / "oppo_detail.json").read_text())

    def request(endpoint: str, method: str, _payload: object) -> object:
        if endpoint.endswith("/pageNew"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("/detail")
        assert method == "GET"
        return detail_response

    jobs = parse("https://careers.oppo.com/campus/post", request, max_workers=1)

    assert jobs[0]["description"] == "负责平台服务研发。\n熟悉 Python。"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "public_api"


def test_oppo_parser_rejects_missing_description() -> None:
    response = {
        "code": 0,
        "data": {
            "records": [{"idRecruitPosition": 1870, "positionName": "平台研发工程师"}],
            "total": 1,
            "pages": 1,
        },
        "msg": "success",
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        if endpoint.endswith("/pageNew"):
            return response
        return {"code": 0, "data": {"idRecruitPosition": 1870, "positionName": "平台研发工程师"}}

    with pytest.raises(ValueError, match="no public description"):
        parse("https://careers.oppo.com/campus/post", request, max_workers=1)
