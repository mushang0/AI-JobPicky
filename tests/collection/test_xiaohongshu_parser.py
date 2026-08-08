import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.xiaohongshu import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_xiaohongshu_parser_reads_list_and_fills_missing_jd_from_detail() -> None:
    list_response = json.loads((FIXTURES / "xiaohongshu_list.json").read_text())
    detail_response = json.loads((FIXTURES / "xiaohongshu_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        if endpoint.endswith("/pageQueryPosition"):
            assert method == "POST"
            assert payload == {
                "label": "all",
                "pageNum": 1,
                "pageSize": 100,
                "recruitType": "intern",
                "themeCode": "THEME-1",
            }
            return list_response
        assert endpoint.endswith("/queryPositionDetail")
        assert method == "GET"
        assert payload == {"positionId": "20821"}
        return detail_response

    jobs = parse(
        "https://job.xiaohongshu.com/campus/position?campusRecruitTypes=term_intern&themeCode=THEME-1",
        request,
    )

    assert len(jobs) == 2
    assert [job["title"] for job in jobs] == [
        "【27届实习】Product Engineer 产品工程师",
        "数据平台工程师",
    ]
    assert (
        jobs[0]["description"] == "负责跨境电商产品的工程实现。\n计算机相关专业，2027届及以后毕业。"
    )
    assert (
        jobs[1]["description"]
        == "参与数据平台服务建设与稳定性优化。\n本科及以上学历，熟悉常用数据处理技术。"
    )
    assert jobs[0]["locations"] == ["北京市", "上海市"]
    assert jobs[1]["locations"] == ["杭州市"]
    assert all(job["recruitment_type"] == "实习" for job in jobs)
    assert jobs[0]["detail_url"] == "https://job.xiaohongshu.com/campus/position/20820"
    metadata = cast(dict[str, object], jobs[1]["metadata"])
    assert metadata["platform_family"] == "xiaohongshu-careers"
    assert metadata["detail_status"] == "public_api"
    assert metadata["list_count"] == 2
    assert len(calls) == 2


def test_xiaohongshu_parser_reads_direct_detail() -> None:
    detail_response = json.loads((FIXTURES / "xiaohongshu_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/queryPositionDetail")
        assert method == "GET"
        assert payload == {"positionId": "20821"}
        return detail_response

    jobs = parse("https://job.xiaohongshu.com/campus/position/20821", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "20821"
    assert jobs[0]["recruitment_type"] == "校招"
    assert calls == [
        (
            "https://job.xiaohongshu.com/websiterecruit/position/queryPositionDetail",
            "GET",
            {"positionId": "20821"},
        )
    ]


def test_xiaohongshu_parser_rejects_social_recruitment() -> None:
    with pytest.raises(ValueError, match="outside the campus parser"):
        parse("https://job.xiaohongshu.com/social/position?recruitType=social", lambda *_: {})
