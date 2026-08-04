import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.tencent import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_tencent_parser_reads_public_list_and_detail_api() -> None:
    list_response = json.loads((FIXTURES / "tencent_list.json").read_text())
    detail_response = json.loads((FIXTURES / "tencent_detail.json").read_text())

    def request(endpoint: str, method: str, _payload: object) -> object:
        if endpoint.endswith("/searchPosition"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("postId=post-001")
        assert method == "GET"
        return detail_response

    jobs = parse("https://join.qq.com/post.html?query=p_14", request)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "post-001"
    assert jobs[0]["title"] == "后台开发"
    assert jobs[0]["description"] == "负责服务端功能开发与维护。\n熟悉一种主流编程语言。"
    assert jobs[0]["locations"] == ["北京", "上海"]
    assert jobs[0]["detail_url"] == "https://join.qq.com/post_detail.html?postid=post-001"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "tencent-campus"
    assert metadata["list_count"] == 1


def test_tencent_parser_rejects_missing_description() -> None:
    list_response = {
        "status": 0,
        "data": {
            "count": 1,
            "positionList": [{"postId": "post-001", "positionTitle": "后台开发"}],
        },
    }

    def request(endpoint: str, _method: str, _payload: object) -> object:
        if endpoint.endswith("/searchPosition"):
            return list_response
        return {"status": 0, "data": {"postId": "post-001"}}

    with pytest.raises(ValueError, match="no public description"):
        parse("https://join.qq.com/post.html?query=p_14", request)
