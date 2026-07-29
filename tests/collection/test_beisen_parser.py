import json

from jobpicky.collection.parsers.beisen import parse


def test_beisen_parser_reads_multiple_jobs_from_embedded_json() -> None:
    html = """
    <html><script type="application/json">
    {"data":{"items":[
      {"jobAdId":"ad-1","jobAdName":"后端工程师","duty":"<p>负责服务开发</p>",
       "detailUrl":"/job/1","applyUrl":"/apply/1","locId":"北京","salary":"10K-20K"},
      {"jobAdId":"ad-2","jobAdName":"测试工程师","detailUrl":"/job/2"}
    ]}}
    </script></html>
    """

    jobs = parse("https://acme.zhiye.com/campus/jobs", lambda _: html)

    assert [job["source_job_id"] for job in jobs] == ["ad-1", "ad-2"]
    assert jobs[0]["title"] == "后端工程师"
    assert jobs[0]["description"] == "负责服务开发"
    assert jobs[0]["detail_url"] == "https://acme.zhiye.com/job/1"
    assert jobs[0]["apply_url"] == "https://acme.zhiye.com/apply/1"
    assert jobs[0]["salary_min"] == 10000
    assert jobs[0]["salary_max"] == 20000


def test_beisen_parser_has_small_static_html_fallback() -> None:
    html = '<ul><li class="job-item"><a href="/job/1">数据分析师</a></li></ul>'

    jobs = parse("https://acme.zhiye.com/jobs", lambda _: html)

    assert len(jobs) == 1
    assert jobs[0]["title"] == "数据分析师"
    assert jobs[0]["detail_url"] == "https://acme.zhiye.com/job/1"


def test_beisen_parser_reads_mobile_listing_and_each_detail() -> None:
    listing = json.dumps(
        {
            "DataResult": [
                {"JobAdId": "101", "JobAdName": "后端工程师"},
                {"JobAdId": "102", "JobAdName": "测试工程师"},
            ]
        }
    )
    details = {
        "https://acme.m.zhiye.com/JobAd/_Info?adid=101": json.dumps(
            {
                "JobAdId": "101",
                "JobAdName": "后端工程师",
                "LocName": "北京",
                "Duty": "服务开发",
                "Require": "本科",
                "DegreeStr": "本科",
                "PostDateStr": "2026-07-01",
                "EndTimeStr": "2026-08-01",
            }
        ),
        "https://acme.m.zhiye.com/JobAd/_Info?adid=102": json.dumps(
            {
                "JobAdId": "102",
                "JobAdName": "测试工程师",
                "LocName": "上海",
                "Duty": "质量保障",
                "EndTimeStr": "2222-02-02",
                "JobAdUrl": "/custom-detail/102",
            }
        ),
    }

    def fetch(url: str) -> str:
        if "_SearchJobAd" in url:
            return listing
        return details[url]

    jobs = parse("https://acme.m.zhiye.com/#/jobs?jc=2", fetch)

    assert [job["source_job_id"] for job in jobs] == ["101", "102"]
    assert jobs[0]["title"] == "后端工程师"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["description"] == "服务开发\n本科"
    assert jobs[0]["published_at"] is not None
    assert jobs[0]["deadline_at"] is not None
    assert jobs[1]["deadline_at"] is None
    assert jobs[0]["detail_url"] == (
        "https://acme.m.zhiye.com/#/jobdetail?id=101&jc=2&isReward=false"
    )
    assert jobs[0]["apply_url"] is None
    assert jobs[1]["detail_url"] == "https://acme.m.zhiye.com/custom-detail/102"

    path_jobs = parse("https://acme.m.zhiye.com/JobAd/List?jc=3", fetch)

    assert path_jobs[0]["detail_url"] == (
        "https://acme.m.zhiye.com/#/jobdetail?id=101&jc=3&isReward=false"
    )

    legacy_jobs = parse("https://acme.m.zhiye.com/job.html?jc=2&c1=1_3", fetch)

    assert legacy_jobs[0]["detail_url"] == (
        "https://acme.m.zhiye.com/jobxq.html?adId=101&jc=2&c1=1_3&c2=-1&ky="
    )


def test_beisen_parser_reads_modern_desktop_campus_api() -> None:
    html = '<script>var BSGlobal = {"PortalId":"portal-1"};</script>'
    response = json.dumps(
        {
            "Code": 200,
            "Count": 1,
            "Data": [
                {
                    "Id": "ad-1",
                    "JobAdId": 123,
                    "JobAdName": "光芯片设计工程师",
                    "Category": "校园招聘",
                    "Duty": "负责芯片设计",
                    "Require": "博士学历",
                    "LocNames": ["成都"],
                    "PostDate": "0001-01-01T00:00:00",
                }
            ],
        }
    )
    requests: list[tuple[str, object]] = []

    def post(url: str, payload: object) -> str:
        requests.append((url, payload))
        return response

    jobs = parse(
        "https://acme.zhiye.com/campus/jobs",
        lambda _: html,
        post,
    )

    assert jobs[0]["source_job_id"] == "ad-1"
    assert jobs[0]["description"] == "负责芯片设计\n博士学历"
    assert jobs[0]["locations"] == ["成都"]
    assert jobs[0]["published_at"] is None
    assert jobs[0]["detail_url"] == "https://acme.zhiye.com/campus/detail?jobAdId=ad-1"
    assert requests[0][0] == "https://acme.zhiye.com/api/Jobad/GetJobAdPageList"
    assert requests[0][1]["Category"] == ["2"]
    assert requests[0][1]["PortalId"] == "portal-1"
    assert "LocId" in requests[0][1]["DisplayFields"]


def test_beisen_parser_falls_back_from_root_to_campus_listing() -> None:
    html = '<script>var BSGlobal = {"PortalId":"portal-1"};</script>'
    response = json.dumps({"Data": [{"Id": "ad-1", "JobAdName": "校招岗位", "Duty": "职责"}]})

    jobs = parse(
        "https://acme.zhiye.com/",
        lambda _: html,
        lambda _url, _payload: response,
    )

    assert [job["source_job_id"] for job in jobs] == ["ad-1"]
    assert jobs[0]["detail_url"] == "https://acme.zhiye.com/campus/detail?jobAdId=ad-1"


def test_beisen_parser_uses_fallback_listing_embedded_json() -> None:
    root_html = "<html>入口页</html>"
    listing_html = """
    <script type="application/json">
    {"data":{"items":[{"jobAdId":"ad-1","jobAdName":"内嵌岗位"}]}}
    </script>
    """

    def fetch(url: str) -> str:
        return listing_html if url.endswith("/campus/jobs") else root_html

    jobs = parse("https://acme.zhiye.com/custom/portal", fetch)

    assert [job["title"] for job in jobs] == ["内嵌岗位"]


def test_beisen_parser_cleans_malformed_mobile_keyword_parameter() -> None:
    listing = json.dumps({"DataResult": [{"JobAdId": "101", "JobAdName": "后端工程师"}]})
    detail = json.dumps({"JobAdId": "101", "JobAdName": "后端工程师", "Duty": "服务开发"})
    listing_urls: list[str] = []

    def fetch(url: str) -> str:
        if "_SearchJobAd" in url:
            listing_urls.append(url)
            return listing
        return detail

    jobs = parse(
        "https://acme.m.zhiye.com/joblist.html?jc=2&ky=π=1&c2=3_35",
        fetch,
    )

    assert len(jobs) == 1
    assert "ky=" in listing_urls[0]
    assert "ky=%CF%80%3D1" not in listing_urls[0]


def test_beisen_parser_filters_modern_desktop_detail() -> None:
    html = '<script>var BSGlobal = {"PortalId":"portal-1"};</script>'
    response = json.dumps(
        {
            "Code": 200,
            "Data": [
                {"Id": "ad-1", "JobAdName": "命中岗位", "Duty": "职责"},
                {"Id": "ad-2", "JobAdName": "其他岗位", "Duty": "职责"},
            ],
        }
    )

    jobs = parse(
        "https://acme.zhiye.com/campus/detail?jobAdId=ad-2",
        lambda _: html,
        lambda _url, _payload: response,
    )

    assert [job["source_job_id"] for job in jobs] == ["ad-2"]
