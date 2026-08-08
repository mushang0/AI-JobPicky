import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.jd import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_jd_parser_reads_list_and_fills_missing_jd_from_detail() -> None:
    list_response = json.loads((FIXTURES / "jd_list.json").read_text())
    detail_response = json.loads((FIXTURES / "jd_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        if endpoint.endswith("/position/page?type=present"):
            assert method == "POST"
            assert payload == {
                "pageSize": 100,
                "pageIndex": 0,
                "parameter": {
                    "positionName": "",
                    "planIdList": [],
                    "jobDirectionCodeList": [],
                    "workCityCodeList": [],
                    "positionDeptList": [],
                },
            }
            return list_response
        assert endpoint.endswith("/position/detail/9070")
        assert method == "POST"
        assert payload == {}
        return detail_response

    jobs = parse("https://campus.jd.com/api/wx/position/index?type=present", request)

    assert len(jobs) == 2
    assert [job["title"] for job in jobs] == ["平台研发工程师", "解决方案工程师"]
    assert jobs[0]["description"] == "负责平台服务研发与性能优化。\n2027届毕业生，本科及以上学历。"
    assert jobs[1]["description"] == (
        "参与客户解决方案设计与落地。\n2027届毕业生，本科及以上学历，具备良好的沟通能力。"
    )
    assert jobs[0]["locations"] == ["北京市-北京市"]
    assert jobs[1]["locations"] == ["广东省-深圳市"]
    assert all(job["recruitment_type"] == "校招" for job in jobs)
    assert jobs[0]["detail_url"] == (
        "https://campus.jd.com/api/wx/position/index?type=present#/details?type=present&id=9039"
    )
    metadata = cast(dict[str, object], jobs[1]["metadata"])
    assert metadata["platform_family"] == "jd-campus"
    assert metadata["detail_status"] == "public_api"
    assert metadata["list_count"] == 2
    assert len(calls) == 2


def test_jd_parser_reads_direct_detail() -> None:
    detail_response = json.loads((FIXTURES / "jd_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/position/detail/9070")
        assert method == "POST"
        assert payload == {}
        return detail_response

    jobs = parse(
        "https://campus.jd.com/api/wx/position/index?type=present#/details?type=present&id=9070",
        request,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "9070"
    assert jobs[0]["recruitment_type"] == "校招"
    assert calls == [
        (
            "https://campus.jd.com/api/wx/position/detail/9070",
            "POST",
            {},
        )
    ]


def test_jd_parser_rejects_missing_public_description() -> None:
    response = {
        "success": True,
        "body": {
            "totalNumber": 1,
            "items": [{"publishId": 9039, "positionName": "平台研发工程师"}],
        },
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        if "/position/page?" in endpoint:
            return response
        return {
            "success": True,
            "body": {"publishId": 9039, "positionName": "平台研发工程师"},
        }

    with pytest.raises(ValueError, match="no title or description"):
        parse("https://campus.jd.com", request, max_workers=1)
