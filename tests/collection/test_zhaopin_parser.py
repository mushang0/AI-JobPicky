from collections.abc import Mapping
from pathlib import Path

import pytest

from jobpicky.collection.parsers.zhaopin import parse

FIXTURES = Path(__file__).parent / "fixtures"
DETAIL_URL = "https://xiaoyuan.zhaopin.com/job/CC123J456"
ZK_URL = "https://example.zhaopin.com/zk/#/join-online"


def test_zhaopin_parser_reads_xiaoyuan_initial_data() -> None:
    page = (DETAIL_URL, (FIXTURES / "zhaopin_initial_data.html").read_text())

    jobs = parse(DETAIL_URL, lambda _url: page)

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source_job_id"] == "CC123J456"
    assert job["title"] == "算法工程师"
    assert job["description"] == "岗位职责：\n负责推荐系统开发。\n岗位要求：硕士。"
    assert job["locations"] == ["北京", "海淀区"]
    assert job["recruitment_type"] == "校招"
    assert job["published_at"].year == 2026  # type: ignore[attr-defined]


def test_zhaopin_parser_reads_zhaokao_public_api() -> None:
    page = ("https://example.zhaopin.com/zk/", (FIXTURES / "zhaopin_zk.html").read_text())

    def request_json(url: str, _headers: object, _payload: object) -> object:
        if url.endswith("/site/portal/pc/site"):
            return {"code": 200, "data": {"siteName": "示例招聘站"}}
        return {
            "code": 200,
            "data": [
                {
                    "id": "job-1",
                    "jobName": "数据分析师",
                    "jobDescription": "负责数据分析",
                    "prvCityArea": "北京市-海淀区",
                    "eduRecord": "本科",
                    "jobGroupName": "校园招聘",
                    "status": 1,
                }
            ],
        }

    jobs = parse(ZK_URL, lambda _url: page, request_json)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "job-1"
    assert jobs[0]["title"] == "数据分析师"
    assert jobs[0]["education_requirement"] == "本科"
    assert jobs[0]["detail_url"] == (
        "https://example.zhaopin.com/zk/#/pages/position-detail/index?id=job-1"
    )


def test_zhaopin_parser_reads_mobile_position_data() -> None:
    url = "https://m.zhaopin.com/xiaoyuan/position/detail?id=CC000059870J40784930211"
    page = (url, (FIXTURES / "zhaopin_mobile_position.html").read_text())

    jobs = parse(url, lambda _url: page)

    assert jobs[0]["source_job_id"] == "CC000059870J40784930211"
    assert jobs[0]["title"] == "飞机维修工程师"
    assert jobs[0]["locations"] == ["厦门"]


def test_zhaopin_parser_paginates_grace_jobs() -> None:
    url = "https://example.zhaopin.com/jobs/index.html"
    page = (
        url,
        "<title>示例校园招聘</title>"
        '<script>var globalData={companyId:"CZ123",companyNumber:"123",'
        'xiaozhaoId:"105123",host:"example",shortHost:"example.zhaopin.com",scene:"cam"}</script>',
    )
    requests: list[Mapping[str, object]] = []

    def request_json(
        _url: str, _headers: Mapping[str, str], payload: Mapping[str, object]
    ) -> object:
        requests.append(payload)
        job_number = f"CC123J{len(requests)}"
        return {
            "code": 200,
            "data": {
                "jobList": [
                    {
                        "job": {
                            "jobNumber": job_number,
                            "title": f"岗位{len(requests)}",
                            "detail": "岗位要求",
                            "cityName": "北京",
                        }
                    }
                ],
                "pageInfo": {"totalPage": 2, "pageIndex": len(requests)},
            },
        }

    jobs = parse(url, lambda _url: page, request_json)

    assert [job["source_job_id"] for job in jobs] == ["CC123J1", "CC123J2"]
    assert len(requests) == 2


def test_zhaopin_parser_rejects_pages_without_public_entry() -> None:
    page = ("https://passport.zhaopin.com/org/login", "<html></html>")
    with pytest.raises(ValueError, match="stable public parser"):
        parse("https://passport.zhaopin.com/org/login", lambda _url: page)
