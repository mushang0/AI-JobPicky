import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.yonyou import parse

FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_URL = "https://career.yonyou.com/SU67ac41886202cc7916ae3029/pb/school.html"


def test_yonyou_parser_reads_form_list_and_public_details() -> None:
    list_response = json.loads((FIXTURES / "yonyou_list.json").read_text())
    detail_response = json.loads((FIXTURES / "yonyou_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        if endpoint.endswith(
            "/listPosition/SU67ac41886202cc7916ae3029?iSaJAx=isAjax&request_locale=zh_CN"
        ):
            assert method == "POST"
            assert payload == {
                "isFrompb": True,
                "recruitType": 1,
                "pageSize": 12,
                "currentPage": 1,
            }
            return list_response
        assert endpoint.endswith(
            "/listPositionDetail/SU67ac41886202cc7916ae3029?iSaJAx=isAjax&request_locale=zh_CN"
        )
        assert method == "POST"
        assert payload == {"postId": "post-2"}
        return detail_response

    jobs = parse(SOURCE_URL, request)

    assert len(jobs) == 2
    assert [job["title"] for job in jobs] == ["软件测试工程师", "算法工程师"]
    assert (
        jobs[1]["description"]
        == "参与算法模型设计、训练与上线。\n熟悉机器学习基础知识，具备良好的编程能力。"
    )
    assert jobs[1]["locations"] == ["上海市"]
    assert all(job["recruitment_type"] == "校招" for job in jobs)
    assert jobs[1]["detail_url"] == (
        "https://career.yonyou.com/SU67ac41886202cc7916ae3029/pb/posDetail.html?postId=post-2&postType=campus"
    )
    metadata = cast(dict[str, object], jobs[1]["metadata"])
    assert metadata["platform_family"] == "yonyou-careers"
    assert metadata["detail_status"] == "public_api"
    assert metadata["list_count"] == 2
    assert len(calls) == 2


def test_yonyou_parser_reads_direct_detail() -> None:
    detail_response = json.loads((FIXTURES / "yonyou_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith(
            "/listPositionDetail/SU67ac41886202cc7916ae3029?iSaJAx=isAjax&request_locale=zh_CN"
        )
        assert method == "POST"
        assert payload == {"postId": "post-2"}
        return detail_response

    jobs = parse(
        "https://career.yonyou.com/SU67ac41886202cc7916ae3029/pb/posDetail.html?postId=post-2&postType=campus",
        request,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "post-2"
    assert jobs[0]["recruitment_type"] == "校招"


def test_yonyou_parser_rejects_a_non_suite_url() -> None:
    with pytest.raises(ValueError, match="no public suite id"):
        parse("https://career.yonyou.com/pb/school.html", lambda *_: {})
