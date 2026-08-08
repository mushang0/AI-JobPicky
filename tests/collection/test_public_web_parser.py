from pathlib import Path

from jobpicky.collection.parsers.public_web import _http_url, parse

FIXTURE = Path(__file__).parent / "fixtures" / "public_job_page.html"
NEXT_FLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "next_flight_job_page.html"


def test_public_web_parser_quotes_non_ascii_request_url_parts() -> None:
    assert _http_url("https://careers.example.test/public/view/42? 对外招聘岗位〈=zh") == (
        "https://careers.example.test/public/view/42?%20%E5%AF%B9%E5%A4%96%E6%8B%9B%E8%81%98%E5%B2%97%E4%BD%8D%E2%8C%A9=zh"
    )


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


def test_public_web_parser_reads_next_flight_job_records() -> None:
    jobs = parse(
        "https://careers.example.test/zh/join-us/job-search",
        lambda _url: NEXT_FLIGHT_FIXTURE.read_text(),
        require_description=True,
    )

    assert jobs[0]["source_job_id"] == "42"
    assert jobs[0]["title"] == "嵌入式工程师"
    assert jobs[0]["description"] == "负责驱动开发 本科及以上"
    assert jobs[0]["locations"] == ["珠海"]
    assert jobs[0]["recruitment_type"] == "校招"
    assert jobs[0]["detail_url"] == "https://careers.example.test/zh/join-us/jobs/demo-job"


def test_public_web_parser_reads_static_job_links() -> None:
    html = '<main><a href="/positions/42">数据分析师</a></main>'

    jobs = parse("https://careers.example.test/jobs", lambda _url: html)

    assert jobs[0]["source_job_id"] == "42"
    assert jobs[0]["title"] == "数据分析师"
    assert jobs[0]["detail_url"] == "https://careers.example.test/positions/42"


def test_public_web_parser_follows_recruitment_navigation() -> None:
    root_url = "https://careers.example.test/"
    pages = {
        root_url: '<a href="/campus">校园招聘</a>',
        "https://careers.example.test/campus": '<a href="/positions/42">算法工程师</a>',
    }

    jobs = parse(root_url, pages.__getitem__)

    assert jobs[0]["title"] == "算法工程师"
    assert jobs[0]["detail_url"] == "https://careers.example.test/positions/42"


def test_public_web_parser_discovers_public_job_api_from_script() -> None:
    root_url = "https://careers.example.test/"
    html = '<script src="/assets/campus.js"></script>'
    script = (
        'const apiPrefix = "https://api.example.test"; const listPath = "/public/api/jobInfo/list";'
    )
    response = (
        '{"result":[{"jobId":"job-1","jobname":"算法工程师",'
        '"jobAddress":"北京","jobRequire":"负责算法开发"}]}'
    )

    def fetch(url: str) -> str:
        if url == root_url:
            return html
        if url.endswith("/assets/campus.js"):
            return script
        if "/public/api/jobInfo/list" in url:
            return response
        raise AssertionError(f"unexpected URL: {url}")

    jobs = parse(root_url, fetch)

    assert jobs[0]["source_job_id"] == "job-1"
    assert jobs[0]["title"] == "算法工程师"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["description"] == "负责算法开发"


def test_public_web_parser_discovers_template_job_api() -> None:
    root_url = "https://careers.example.test/plugins/career_site/sites/default"
    html = """
    <script>
      const publicBaseUrl = 'https://careers.example.test';
      const tenantSlug = 'default';
      const pluginPath = '/plugins/career_site';
      const jobsPath = `/api/${encodeURIComponent(tenantSlug)}/jobs`;
    </script>
    """
    response = (
        '{"data":{"items":[{"job_id":"job-2","title":"安全工程师",'
        '"location":"上海","description":"负责安全研究"}]}}'
    )

    def fetch(url: str) -> str:
        if url == root_url:
            return html
        if "/plugins/career_site/api/default/jobs" in url:
            return response
        raise AssertionError(f"unexpected URL: {url}")

    jobs = parse(root_url, fetch)

    assert jobs[0]["source_job_id"] == "job-2"
    assert jobs[0]["title"] == "安全工程师"
    assert jobs[0]["locations"] == ["上海"]


def test_public_web_parser_enriches_list_jobs_with_public_detail_api() -> None:
    root_url = "https://careers.example.test/"
    html = """
    <script>
      const apiPrefix = 'https://api.example.test';
      const listPath = '/public/api/jobInfo/list';
      const detailPath = '/public/api/jobInfo/detail';
    </script>
    """
    list_response = '{"result":[{"jobId":"job-3","jobname":"产品经理"}]}'
    detail_response = (
        '{"data":{"jobId":"job-3","jobname":"产品经理","description":"负责产品规划与需求分析"}}'
    )

    def fetch(url: str) -> str:
        if url == root_url:
            return html
        if "/public/api/jobInfo/list" in url:
            return list_response
        if "/public/api/jobInfo/detail" in url:
            return detail_response
        raise AssertionError(f"unexpected URL: {url}")

    jobs = parse(root_url, fetch)

    assert jobs[0]["title"] == "产品经理"
    assert jobs[0]["description"] == "负责产品规划与需求分析"
    assert jobs[0]["metadata"] == {"parser": "public_web", "record_kind": "job"}


def test_public_web_parser_uses_numeric_detail_id_when_list_has_a_job_code() -> None:
    root_url = "https://careers.example.test/"
    html = """
    <script>
      const apiPrefix = 'https://api.example.test';
      const listPath = '/public/api/jobInfo/list';
      const detailPath = '/public/api/jobInfo/detail';
    </script>
    """
    list_response = '{"result":[{"code":"A-42","id":42,"jobname":"算法工程师"}]}'
    detail_response = (
        '{"data":{"code":"A-42","id":42,"jobname":"算法工程师","description":"负责算法开发"}}'
    )

    def fetch(url: str) -> str:
        if url == root_url:
            return html
        if "/public/api/jobInfo/list" in url:
            return list_response
        if "/public/api/jobInfo/detail" in url and "job_id=42" in url:
            return detail_response
        raise AssertionError(f"unexpected URL: {url}")

    jobs = parse(root_url, fetch)

    assert jobs[0]["source_job_id"] == "A-42"
    assert jobs[0]["description"] == "负责算法开发"


def test_public_web_parser_can_require_job_description() -> None:
    html = '<main><a href="/positions/42">数据分析师</a></main>'

    assert (
        parse(
            "https://careers.example.test/jobs",
            lambda _url: html,
            require_description=True,
        )
        == []
    )


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
