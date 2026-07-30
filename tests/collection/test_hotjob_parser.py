import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from jobpicky.collection.parsers.hotjob import parse

FIXTURES = Path(__file__).parent / "fixtures"
LIST_URL = "https://wecruit.hotjob.cn/SU1234567890abcdef/pb/school.html"
DETAIL_URL = (
    f"{LIST_URL.replace('/pb/school.html', '/mc/detail')}?postId=post-001&recruitType=campus"
)


def _fixture(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_hotjob_parser_reads_listing_and_public_detail() -> None:
    def fetch(url: str, _data: object) -> object:
        return (
            _fixture("hotjob_detail.json")
            if "listPositionDetail" in url
            else _fixture("hotjob_list.json")
        )

    jobs = parse(LIST_URL, fetch)

    assert jobs[0]["source_job_id"] == "post-001"
    assert jobs[0]["title"] == "软件工程师"
    assert jobs[0]["description"] == (
        "岗位职责\n参与服务端功能开发。\n\n申请要求\n本科及以上学历。\n\n专业要求\n计算机相关专业"
    )
    assert jobs[0]["locations"] == ["北京", "苏州"]
    assert jobs[0]["recruitment_type"] == "校招"
    assert jobs[0]["education_requirement"] == "本科及以上"
    metadata = jobs[0]["metadata"]
    detail_url = jobs[0]["detail_url"]
    assert isinstance(metadata, dict)
    assert metadata["detail_status"] == "ok"
    assert isinstance(detail_url, str)
    assert "postId=post-001" in detail_url


def test_hotjob_parser_reads_direct_detail() -> None:
    calls: list[str] = []

    def fetch(url: str, data: object) -> object:
        calls.append(url)
        return _fixture("hotjob_detail.json")

    jobs = parse(DETAIL_URL, fetch)

    assert len(jobs) == 1
    assert jobs[0]["source_ref"] == jobs[0]["detail_url"]
    assert any("listPositionDetail" in url for url in calls)


def test_hotjob_parser_preserves_list_job_when_detail_is_unavailable() -> None:
    def fetch(url: str, _data: object) -> object:
        if "listPositionDetail" in url:
            raise ValueError("temporary detail failure")
        return _fixture("hotjob_list.json")

    jobs = parse(LIST_URL, fetch)

    assert jobs[0]["title"] == "软件工程师"
    assert jobs[0]["description"] is None
    metadata = jobs[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["detail_status"] == "unavailable-fallback"


def test_hotjob_parser_rejects_empty_listing() -> None:
    response = _fixture("hotjob_list.json")
    response["data"]["pageForm"]["pageData"] = []  # type: ignore[index]

    with pytest.raises(ValueError, match="no jobs"):
        parse(LIST_URL, lambda _url, _data: response)


def test_hotjob_parser_maps_direct_recruitment_type() -> None:
    jobs = parse(DETAIL_URL, lambda _url, _data: _fixture("hotjob_detail.json"))
    detail_url = jobs[0]["detail_url"]
    assert isinstance(detail_url, str)
    query = parse_qs(urlsplit(detail_url).query)

    assert query["recruitType"] == ["campus"]


def test_hotjob_parser_supports_public_wt_html_and_json_endpoints() -> None:
    root_url = "https://legacy.hotjob.cn/"
    page_url = "https://legacy.hotjob.cn/wt/DEMO/web/index/CompDemoRecruitcampus"
    page_html = """
    <input id="recruitTypeV" value="1">
    <script>
      var surl = "/wt/DEMO/web/json/position/list?operational=public-list";
      var url = "/wt/DEMO/web/json/position/detail?operational=public-detail";
    </script>
    """
    list_response = {
        "req_state": 200,
        "pageCount": 1,
        "postList": [
            {
                "postId": "wt-001",
                "postName": "测试岗位",
                "postType": "研发类",
                "orgName": "示例公司",
                "workPlace": "北京",
                "publishDate": "2026-07-01",
                "recruitType": 1,
            }
        ],
    }
    detail_response = {
        "req_state": 9200,
        "postInfo": {
            "postId": "wt-001",
            "postName": "测试岗位",
            "postType": "研发类",
            "companyName": "示例公司",
            "workPlace": "北京",
            "workConcet": "负责研发工作。",
            "education": "本科",
            "publishDate": "2026-07-01",
            "endDate": "2026-08-31",
            "recruitType": 1,
        },
    }

    def fetch_html(url: str) -> str:
        return f'<iframe src="{page_url}"></iframe>' if url == root_url else page_html

    def fetch_get(url: str, _data: object) -> object:
        return detail_response if "/position/detail" in url else list_response

    jobs = parse(root_url, fetch_get=fetch_get, fetch_html=fetch_html)

    assert jobs[0]["source_job_id"] == "wt-001"
    assert jobs[0]["description"] == "岗位职责\n负责研发工作。"
    metadata = jobs[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["detail_status"] == "ok"
