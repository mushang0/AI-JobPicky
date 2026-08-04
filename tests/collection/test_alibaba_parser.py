import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.alibaba import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_alibaba_parser_reads_public_list_api() -> None:
    list_response = json.loads((FIXTURES / "alibaba_list.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/position/search")
        assert method == "POST"
        assert payload == {
            "batchId": 100000700001,
            "pageIndex": 1,
            "pageSize": 100,
            "channel": "new_campus_group_official_site",
            "language": "zh",
        }
        return list_response

    jobs = parse("https://campus-talent.alibaba.com/campus/position?batchId=100000700001", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "alibaba-job-001"
    assert jobs[0]["description"] == "参与平台功能开发。\n具备良好的工程基础。"
    assert jobs[0]["locations"] == ["杭州"]
    assert jobs[0]["detail_url"] == (
        "https://campus-talent.alibaba.com/campus/position/alibaba-job-001"
    )
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "alibaba-campus"
    assert metadata["detail_status"] == "list_api"
    assert metadata["list_count"] == 1


def test_alibaba_parser_preserves_filter_params() -> None:
    list_response = json.loads((FIXTURES / "alibaba_list.json").read_text())
    encoded_filters = "%7B%22customDept%22%3A%5B%22dept-a%22%2C%22dept-b%22%5D%7D"

    def request(_endpoint: str, _method: str, payload: object) -> object:
        assert payload == {
            "batchId": 100000540002,
            "pageIndex": 1,
            "pageSize": 100,
            "channel": "new_campus_group_official_site",
            "language": "zh",
            "customDeptCode": "dept-a,dept-b",
        }
        return list_response

    jobs = parse(
        "https://campus-talent.alibaba.com/campus/position?batchId=100000540002&"
        f"filterParams={encoded_filters}",
        request,
    )

    assert len(jobs) == 1


def test_alibaba_parser_fetches_detail_when_list_has_no_description() -> None:
    list_response = {
        "success": True,
        "content": {
            "currentPage": 1,
            "pageSize": 100,
            "totalCount": 1,
            "datas": [{"id": "alibaba-job-001", "name": "平台研发工程师"}],
        },
    }
    detail_response = json.loads((FIXTURES / "alibaba_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/position/search"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("/position/detail")
        assert method == "POST"
        assert payload == {
            "id": "alibaba-job-001",
            "channel": "new_campus_group_official_site",
            "language": "zh",
        }
        return detail_response

    jobs = parse("https://campus-talent.alibaba.com/campus/position?batchId=100000700001", request)

    assert len(jobs) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "public_api"


def test_alibaba_parser_keeps_direct_detail_scoped() -> None:
    detail_response = json.loads((FIXTURES / "alibaba_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/position/detail")
        assert method == "POST"
        return detail_response

    jobs = parse(
        "https://campus-talent.alibaba.com/campus/position/alibaba-job-001",
        request,
    )

    assert len(jobs) == 1
    assert calls == [
        (
            "https://campus-talent.alibaba.com/position/detail",
            "POST",
            {
                "id": "alibaba-job-001",
                "channel": "new_campus_group_official_site",
                "language": "zh",
            },
        )
    ]


def test_alibaba_parser_rejects_invalid_filter_params() -> None:
    with pytest.raises(ValueError, match="invalid filterParams"):
        parse(
            "https://campus-talent.alibaba.com/campus/position?batchId=100000700001&"
            "filterParams=%7Binvalid",
            lambda _endpoint, _method, _payload: {},
        )
