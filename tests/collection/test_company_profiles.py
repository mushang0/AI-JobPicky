from dataclasses import replace
from datetime import UTC, datetime

import pytest

from jobpicky.collection.company_profiles import find_company_profile
from jobpicky.collection.pipeline import merge_job_fields
from jobpicky.collection.spreadsheet import SpreadsheetRow


def make_row(*links: str) -> SpreadsheetRow:
    return SpreadsheetRow(
        row_number=12,
        updated_at=None,
        company_name="表格公司",
        company_nature="民企",
        industry="软件",
        job_directions="后端, 前端",
        locations=["表格地点"],
        deadline_at=datetime(2026, 8, 20, tzinfo=UTC),
        graduation_years=[2027],
        education_requirement="本科",
        batch="秋招专场",
        announcement_source="公告来源",
        announcement_url="https://example.com/notice",
        apply_links=list(links),
        major_requirement="计算机相关专业",
        has_written_test="有笔试",
    )


def test_profile_matches_company_group_and_platform_domain() -> None:
    profile = find_company_profile(
        "https://campus-talent.alibaba.com/campus/position?batchId=100000700001",
        "阿里巴巴-虎鲸文娱集团",
    )

    assert profile is not None
    assert profile.group_id == "alibaba"
    assert profile.platform_family == "alibaba-campus"
    assert profile.priority == "P0"


def test_profile_does_not_match_unknown_domain() -> None:
    assert find_company_profile("https://careers.example.test/jobs", "示例公司") is None


def test_shared_recruitment_host_requires_company_alias() -> None:
    assert find_company_profile("https://www.liepin.com/job/123") is None
    profile = find_company_profile("https://www.liepin.com/job/123", "奇瑞捷豹路虎")
    assert profile is not None
    assert profile.group_id == "chery-jlr"


@pytest.mark.parametrize(
    ("url", "company", "platform_family"),
    [
        (
            "https://jobs.ecoflow.com/602892/position/list",
            "正浩EcoFlow",
            "feishu-careers",
        ),
        (
            "https://career.papegames.com/campus/position/list",
            "叠纸游戏",
            "feishu-careers",
        ),
        (
            "https://xiaomi.jobs.f.mioffice.cn/toptalent",
            "小米",
            "feishu-careers",
        ),
        (
            "https://campus.sonoscape.com/campus-recruitment/sonoscape/94392/",
            "开立医疗",
            "moka-careers",
        ),
        (
            "https://campus.fingard.com/campus_apply/baorong/25901/",
            "保融科技",
            "moka-careers",
        ),
        (
            "https://careers.oppo.com/university/oppo/campus/post",
            "OPPO",
            "oppo-careers",
        ),
        ("https://campus.jd.com", "京东", "jd-campus"),
        ("https://outreach.didichuxing.com/elite/", "滴滴", "didi-careers"),
        (
            "https://job.xiaohongshu.com/campus/position?campusRecruitTypes=term_intern",
            "小红书",
            "xiaohongshu-careers",
        ),
        (
            "https://job.zte.com.cn/cn/campus-recruitment/Recruitment_positions/freshstudent.html",
            "中兴通讯",
            "zte-careers",
        ),
        (
            "https://career.yonyou.com/SU67ac41886202cc7916ae3029/pb/school.html",
            "用友",
            "yonyou-careers",
        ),
        (
            "https://apply.careers.dji.com/campus-recruitment/dji/143359",
            "DJI",
            "moka-careers",
        ),
    ],
)
def test_custom_domains_reuse_verified_platform_families(
    url: str, company: str, platform_family: str
) -> None:
    profile = find_company_profile(url, company)

    assert profile is not None
    assert profile.platform_family == platform_family


def test_collected_job_records_company_profile_metadata() -> None:
    job = merge_job_fields(
        "source-1",
        replace(make_row("https://join.qq.com/post.html?query=p_14"), company_name="腾讯"),
        {"source_job_id": "job-1", "title": "后台开发"},
    )

    assert job.metadata["company_group"] == "tencent"
    assert job.metadata["company_profile"] == "腾讯"
    assert job.metadata["platform_family"] == "tencent-campus"
    assert job.metadata["profile_priority"] == "P0"
