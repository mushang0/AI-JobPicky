import pytest

from jobpicky.collection.parsers import company_recruitment


@pytest.mark.parametrize(
    ("url", "platform_family"),
    [
        ("https://jobs.ecoflow.com/602892/position/list", "feishu-careers"),
        (
            "https://campus.sonoscape.com/campus-recruitment/sonoscape/94392/",
            "moka-careers",
        ),
        (
            "https://careers.oppo.com/university/oppo/campus/post",
            "oppo-careers",
        ),
        ("https://zhaopin.meituan.com/web/beidou", "meituan-campus"),
        ("https://jobs.bilibili.com/campus/positions", "bilibili-careers"),
        (
            "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html",
            "huawei-careers",
        ),
        ("https://campus.jd.com", "jd-campus"),
        ("https://outreach.didichuxing.com/elite/", "didi-careers"),
        ("https://job.xiaohongshu.com/campus/position", "xiaohongshu-careers"),
        (
            "https://job.zte.com.cn/cn/campus-recruitment/Recruitment_positions/freshstudent.html",
            "zte-careers",
        ),
        (
            "https://career.yonyou.com/SU67ac41886202cc7916ae3029/pb/school.html",
            "yonyou-careers",
        ),
    ],
)
def test_company_recruitment_dispatches_custom_domains_by_platform(
    monkeypatch: pytest.MonkeyPatch, url: str, platform_family: str
) -> None:
    def parser(_: str) -> list[dict[str, object]]:
        return [{"source_job_id": platform_family, "title": "平台岗位"}]

    monkeypatch.setitem(company_recruitment._PLATFORM_PARSERS, platform_family, parser)

    jobs = company_recruitment.parse(url)

    assert jobs == [{"source_job_id": platform_family, "title": "平台岗位"}]
