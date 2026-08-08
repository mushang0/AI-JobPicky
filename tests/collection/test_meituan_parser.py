import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.meituan import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_meituan_parser_reads_filtered_list_and_public_detail() -> None:
    list_response = json.loads((FIXTURES / "meituan_list.json").read_text())
    detail_response = json.loads((FIXTURES / "meituan_detail.json").read_text())
    detail_calls: list[object] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/getJobList"):
            assert method == "POST"
            assert payload == {
                "page": {"pageNo": 1, "pageSize": 500},
                "jobShareType": "1",
                "keywords": "",
                "cityList": [],
                "department": [],
                "jfJgList": [],
                "jobType": [
                    {"code": "1", "subCode": ["1-3"]},
                    {"code": "2", "subCode": ["2-3"]},
                ],
                "typeCode": ["1-3", "2-3"],
                "specialCode": [],
            }
            return list_response
        assert endpoint.endswith("/getJobDetail")
        assert method == "POST"
        detail_calls.append(payload)
        assert payload == {"jobUnionId": "mt-job-002"}
        return detail_response

    jobs = parse("https://zhaopin.meituan.com/web/beidou", request, max_workers=1)

    assert [job["source_job_id"] for job in jobs] == ["mt-job-001", "mt-job-002"]
    assert jobs[0]["description"] == "参与平台服务开发。\n熟悉 Python。"
    assert jobs[1]["description"] == "参与数据分析项目。\n具备良好的数据基础。"
    assert jobs[0]["locations"] == ["北京市"]
    assert jobs[0]["recruitment_type"] == "校招"
    assert jobs[1]["recruitment_type"] == "实习"
    assert jobs[0]["detail_url"] == (
        "https://zhaopin.meituan.com/web/position/detail?"
        "jobUnionId=mt-job-001&jobShareType=1&highlightType=campus"
    )
    assert detail_calls == [{"jobUnionId": "mt-job-002"}]
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "meituan-campus"
    assert metadata["list_count"] == 2


def test_meituan_parser_rejects_missing_public_description() -> None:
    list_response = {
        "status": 1,
        "data": {
            "list": [{"jobUnionId": "mt-job-001", "name": "平台岗位"}],
            "page": {"totalCount": 1, "totalPage": 1},
        },
    }
    detail_response = {
        "status": 1,
        "data": {"jobUnionId": "mt-job-001", "name": "平台岗位"},
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        return list_response if endpoint.endswith("/getJobList") else detail_response

    with pytest.raises(ValueError, match="no public description"):
        parse("https://zhaopin.meituan.com/web/beidou", request, max_workers=1)


def test_meituan_parser_scopes_direct_position_link() -> None:
    detail_response = json.loads((FIXTURES / "meituan_detail.json").read_text())
    calls: list[str] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append(endpoint)
        assert endpoint.endswith("/getJobDetail")
        assert method == "POST"
        assert payload == {"jobUnionId": "mt-job-002"}
        return detail_response

    jobs = parse(
        "https://zhaopin.meituan.com/web/position/detail?jobUnionId=mt-job-002",
        request,
        max_workers=1,
    )

    assert [job["source_job_id"] for job in jobs] == ["mt-job-002"]
    assert calls == ["https://zhaopin.meituan.com/api/official/job/getJobDetail"]
