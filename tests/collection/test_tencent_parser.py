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


def test_tencent_parser_reads_qingyun_topic_jd_fields() -> None:
    list_response = {
        "status": 0,
        "data": {
            "count": 1,
            "positionList": [
                {
                    "postId": "topic-post-001",
                    "positionTitle": "腾讯营销—大模型推荐研究",
                    "projectName": "青云计划-应届生",
                    "workCities": "上海",
                }
            ],
        },
    }
    detail_response = {
        "status": 0,
        "data": {
            "postId": "topic-post-001",
            "title": "腾讯营销—大模型推荐研究",
            "desc": "",
            "request": "",
            "workCityList": ["上海"],
            "topicDetail": "负责推荐模型和 Agent 研究。",
            "topicRequirement": "硕士及以上，熟悉深度学习框架。",
        },
    }

    def request(endpoint: str, method: str, _payload: object) -> object:
        if endpoint.endswith("/searchPosition"):
            assert method == "POST"
            return list_response
        assert endpoint.endswith("postId=topic-post-001")
        assert method == "GET"
        return detail_response

    jobs = parse("https://join.qq.com/post.html?query=p_14", request, max_workers=1)

    assert jobs[0]["description"] == ("负责推荐模型和 Agent 研究。\n硕士及以上，熟悉深度学习框架。")


def test_tencent_parser_skips_explicitly_closed_positions() -> None:
    list_response = {
        "status": 0,
        "data": {
            "count": 2,
            "positionList": [
                {"postId": "open-001", "positionTitle": "后台开发"},
                {"postId": "closed-001", "positionTitle": "已下架岗位"},
            ],
        },
    }
    open_detail = {
        "status": 0,
        "data": {
            "postId": "open-001",
            "desc": "负责服务端开发。",
            "request": "熟悉一种编程语言。",
            "workCityList": ["深圳"],
        },
    }
    closed_detail = {"status": 404, "message": "岗位已下架", "data": None}

    def request(endpoint: str, method: str, _payload: object) -> object:
        if endpoint.endswith("/searchPosition"):
            assert method == "POST"
            return list_response
        assert method == "GET"
        return closed_detail if "closed-001" in endpoint else open_detail

    jobs = parse("https://join.qq.com/post.html?query=p_14", request, max_workers=1)

    assert len(jobs) == 1
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["closed_position_count"] == 1
