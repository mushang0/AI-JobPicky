from pathlib import Path

import pytest

from jobpicky.collection.parsers.wechat import parse

FIXTURE = Path(__file__).parent / "fixtures" / "wechat_article.html"
URL = "https://mp.weixin.qq.com/s/article-001?scene=1"


def test_wechat_parser_creates_one_announcement_record() -> None:
    jobs = parse(URL, lambda _url: FIXTURE.read_text())

    assert len(jobs) == 1
    job = jobs[0]
    assert job["source_job_id"] == "article-001"
    assert job["title"] == "示例公司2027校园招聘"
    assert job["description"] == "我们正在寻找软件工程师。 工作地点：北京"
    assert job["recruitment_type"] == "校招"
    assert job["published_at"].year == 2026  # type: ignore[attr-defined]
    detail_url = job["detail_url"]
    assert isinstance(detail_url, str)
    assert "scene=1" in detail_url
    metadata = job["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["record_kind"] == "wechat_announcement"


def test_wechat_parser_rejects_non_article_url() -> None:
    with pytest.raises(ValueError, match="article id"):
        parse("https://mp.weixin.qq.com/", lambda _url: FIXTURE.read_text())


def test_wechat_parser_requires_title() -> None:
    with pytest.raises(ValueError, match="no public title"):
        parse(URL, lambda _url: "<html><div id='js_content'>正文</div></html>")
