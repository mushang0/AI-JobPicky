import json
import threading
import time
from pathlib import Path

import pytest

from jobpicky.collection.parsers.feishu import (
    BrowserUnavailableError,
    ClosedJobError,
    discover_detail_urls,
    parse,
)

FIXTURE = Path(__file__).parent / "fixtures" / "feishu_detail.json"
DETAIL_URL = "https://momenta.jobs.feishu.cn/campus/position/7665627986519296266/detail"


def fixture_response() -> object:
    return json.loads(FIXTURE.read_text())


def test_feishu_parser_reads_complete_public_detail() -> None:
    jobs = parse(DETAIL_URL, lambda _url, _path: fixture_response())

    assert jobs == [
        {
            "source_job_id": "7665627986519296266",
            "title": "2027届-嵌入式软件工程师",
            "description": "职位描述\n负责车载系统开发。\n\n职位要求\n本科及以上学历。",
            "locations": ["北京", "苏州"],
            "detail_url": DETAIL_URL,
            "apply_url": DETAIL_URL,
            "recruitment_type": "校招",
            "published_at": jobs[0]["published_at"],
            "source_ref": DETAIL_URL,
            "metadata": {
                "department": "系统研发部",
                "job_function": "软件研发",
                "required_degree_code": 6,
                "channel_online_status": 1,
            },
        }
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://duxiaoman.jobs.feishu.cn/051736/position/7649303782597691694/detail",
        "https://tcnrm7b535t2.jobs.feishu.cn/748205/position/7644923888778840339/detail?spread=x",
        "https://micoworld.jobs.feishu.cn/index/position/7641106184007928105/detail",
        "https://jobs.ecoflow.com/602892/position/7662352504873077011/detail",
        "https://career.papergames.com/campus/position/7660119389676734761/detail",
        "https://xiaomi.jobs.f.mioffice.cn/toptalent/position/7665295778067368238/detail",
    ],
)
def test_feishu_parser_accepts_real_detail_path_templates(url: str) -> None:
    jobs = parse(url, lambda _url, _path: fixture_response())

    assert jobs[0]["source_job_id"] == "7665627986519296266"


def test_feishu_parser_reports_closed_job() -> None:
    response = fixture_response()
    response["data"]["job_post_detail"]["channel_online_status"] = 0  # type: ignore[index]

    with pytest.raises(ClosedJobError, match="closed"):
        parse(DETAIL_URL, lambda _url, _path: response)


def test_feishu_listing_discovers_cards_then_reads_details() -> None:
    listing_url = "https://momenta.jobs.feishu.cn/campus/"
    html = """
    <a href="/campus/position/101/detail">岗位一</a>
    <a href="/campus/position/102/detail">岗位二</a>
    """

    def fetch(api_url: str, _website_path: str) -> object:
        job_id = api_url.split("/job/posts/", 1)[1].split("?", 1)[0]
        response = fixture_response()
        detail = response["data"]["job_post_detail"]  # type: ignore[index]
        detail["id"] = job_id
        detail["title"] = f"岗位{job_id}"
        return response

    jobs = parse(listing_url, fetch, lambda _: html)

    assert [job["source_job_id"] for job in jobs] == ["101", "102"]
    assert all(job["description"] for job in jobs)


def test_feishu_listing_deduplicates_links() -> None:
    html = """
    <a href="/campus/position/101/detail">岗位</a>
    <a href="/campus/position/101/detail">重复岗位</a>
    """

    links = discover_detail_urls("https://momenta.jobs.feishu.cn/campus/", lambda _: html)

    assert links == ["https://momenta.jobs.feishu.cn/campus/position/101/detail"]


def test_feishu_listing_follows_rendered_position_navigation() -> None:
    root_url = "https://radrocktech.jobs.feishu.cn/531403/?spread=Q13728Z"
    root_html = '<a href="/531403/position/list">职位</a>'
    listing_html = '<a href="/531403/position/101/detail?spread=Q13728Z">岗位一</a>'
    rendered: list[str] = []

    def render(url: str) -> str:
        rendered.append(url)
        return root_html if url == root_url else listing_html

    def fetch(api_url: str, _website_path: str) -> object:
        response = fixture_response()
        detail = response["data"]["job_post_detail"]  # type: ignore[index]
        detail["id"] = api_url.split("/job/posts/", 1)[1].split("?", 1)[0]
        detail["title"] = "岗位一"
        return response

    jobs = parse(root_url, fetch, render)

    assert [job["source_job_id"] for job in jobs] == ["101"]
    assert any("/531403/position/list" in url for url in rendered)
    assert all("spread=Q13728Z" in url for url in rendered if "/position/list" in url)


def test_feishu_listing_can_find_a_route_in_page_configuration() -> None:
    root_url = "https://kwh0jtf778.jobs.feishu.cn/229043/"
    root_html = '<script type="application/json">{"path":"/position/list"}</script>'
    listing_html = '<a href="/229043/position/101/detail">岗位一</a>'

    def fetch(api_url: str, _website_path: str) -> object:
        response = fixture_response()
        detail = response["data"]["job_post_detail"]  # type: ignore[index]
        detail["id"] = api_url.split("/job/posts/", 1)[1].split("?", 1)[0]
        return response

    jobs = parse(
        root_url,
        fetch,
        lambda url: root_html if url == root_url else listing_html,
    )

    assert [job["source_job_id"] for job in jobs] == ["101"]


def test_feishu_listing_retries_without_stale_listing_filters() -> None:
    root_url = "https://tarsrobot.jobs.feishu.cn/021343/?project=stale&spread=track"
    root_html = '<script type="application/json">{"path":"/position/list"}</script>'
    listing_html = '<a href="/021343/position/101/detail?spread=track">岗位一</a>'
    rendered: list[str] = []

    def render(url: str) -> str:
        rendered.append(url)
        return root_html if url == root_url else ("" if "project=stale" in url else listing_html)

    links = discover_detail_urls(root_url, render)

    assert links == ["https://tarsrobot.jobs.feishu.cn/021343/position/101/detail?spread=track"]
    assert any("project=stale" in url for url in rendered)
    assert any("spread=track" in url and "project=stale" not in url for url in rendered)


def test_feishu_listing_reads_direct_cards_from_a_project_page() -> None:
    url = "https://tarsrobot.jobs.feishu.cn/021343/?keywords=&project=&current=1&limit=10"
    html = """
    <a>招聘项目</a>
    <a href="/021343/position/101/detail">岗位一</a>
    <a href="/021343/position/102/detail">岗位二</a>
    """

    def fetch(api_url: str, _website_path: str) -> object:
        response = fixture_response()
        detail = response["data"]["job_post_detail"]  # type: ignore[index]
        detail["id"] = api_url.split("/job/posts/", 1)[1].split("?", 1)[0]
        detail["title"] = f"岗位{detail['id']}"
        return response

    jobs = parse(url, fetch, lambda _: html)

    assert [job["source_job_id"] for job in jobs] == ["101", "102"]


def test_feishu_listing_uses_more_parallel_detail_requests() -> None:
    html = "".join(f'<a href="/021343/position/{number}/detail">岗位</a>' for number in range(240))
    state = {"active": 0, "maximum": 0}
    lock = threading.Lock()

    def fetch(api_url: str, _website_path: str) -> object:
        with lock:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.01)
        with lock:
            state["active"] -= 1
        response = fixture_response()
        detail = response["data"]["job_post_detail"]  # type: ignore[index]
        detail["id"] = api_url.split("/job/posts/", 1)[1].split("?", 1)[0]
        return response

    jobs = parse("https://tarsrobot.jobs.feishu.cn/021343/", fetch, lambda _: html)

    assert len(jobs) == 240
    assert state["maximum"] >= 8


def test_feishu_listing_reports_missing_browser() -> None:
    def unavailable(_url: str) -> str:
        raise BrowserUnavailableError("Chromium not found")

    with pytest.raises(BrowserUnavailableError, match="Chromium"):
        parse(
            "https://momenta.jobs.feishu.cn/campus/",
            lambda _url, _path: {},
            unavailable,
        )


def test_feishu_listing_rejects_invalid_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBPICKY_FEISHU_WORKERS", "0")

    with pytest.raises(ValueError, match="at least 1"):
        parse("https://momenta.jobs.feishu.cn/campus/", render=lambda _: "")
