from pathlib import Path

from jobpicky.collection.parsers.public_web import parse

FIXTURE = Path(__file__).parent / "fixtures" / "public_job_page.html"


def test_public_web_parser_reads_json_ld_job_posting() -> None:
    jobs = parse(
        "https://careers.example.test/jobs/demo-job-1",
        lambda _url: FIXTURE.read_text(),
    )

    assert jobs[0]["source_job_id"] == "demo-job-1"
    assert jobs[0]["title"] == "后端工程师"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["salary_min"] == 12000
    assert jobs[0]["salary_max"] == 18000
    assert jobs[0]["detail_url"] == "https://careers.example.test/jobs/demo-job-1"


def test_public_web_parser_reads_static_job_links() -> None:
    html = '<main><a href="/positions/42">数据分析师</a></main>'

    jobs = parse("https://careers.example.test/jobs", lambda _url: html)

    assert jobs[0]["source_job_id"] == "42"
    assert jobs[0]["title"] == "数据分析师"
    assert jobs[0]["detail_url"] == "https://careers.example.test/positions/42"


def test_public_web_parser_reads_aircas_server_rendered_cards() -> None:
    listing = """
    <a class="box-title h18" href="javascript:void(0);"
       onclick="viewPositionInfo(&quot;position-1&quot;,null)">雷达算法工程师</a>
    """

    jobs = parse(
        "https://zhaopin.aircas.ac.cn/index",
        lambda url: listing if "positionSearchByCondition" in url else "<html></html>",
    )

    assert jobs[0]["source_job_id"] == "position-1"
    assert jobs[0]["detail_url"] == (
        "https://zhaopin.aircas.ac.cn/system/userInfo/positionInfo?id=position-1"
    )


def test_public_web_parser_does_not_turn_a_login_page_into_a_job() -> None:
    assert parse("https://careers.example.test/login", lambda _url: "<title>登录</title>") == []


def test_public_web_parser_can_keep_a_recruitment_announcement_as_a_record() -> None:
    html = """
    <html><head><title>示例公司2027年校园招聘公告</title></head>
    <body><article>现公开招聘软件工程师，欢迎报名。</article></body></html>
    """

    jobs = parse(
        "https://www.example.test/notices/2027-campus-recruitment.html",
        lambda _url: html,
        allow_announcement=True,
    )

    assert jobs[0]["metadata"] == {
        "parser": "public_web",
        "record_kind": "public_announcement",
    }
    assert jobs[0]["apply_url"] is None
