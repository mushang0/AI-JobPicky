import pytest

from jobpicky.collection.link_classification import classify_link


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://app.mokahr.com/campus-recruitment/acme?source=wechat#apply", "MOKA"),
        ("https://campus.beisen.com/jobs/detail?id=123&from=qr#intro", "BEISEN"),
        ("https://esunsoft.zhiye.com/", "BEISEN"),
        ("https://kjgb.zhiye.com/", "BEISEN"),
        ("https://example.zhiye.com/campus", "BEISEN"),
        (
            "https://young.yingjiesheng.com/xyzlogin?jumpurl=https://xyz.51job.com/External/Others/Login51.aspx?CtmID=1&prd=campus",
            "JOB_51",
        ),
        ("https://acme.jobs.feishu.cn/campus/position/list?current=1#jobs", "FEISHU"),
        ("https://wecruit.hotjob.cn/wt/abc/web/index?jobId=1#apply", "HOTJOB"),
        ("https://xiaoyuan.zhaopin.com/job/CC123?keyword=ai#detail", "ZHAOPIN"),
        ("https://xyz.51job.com/External/Apply.aspx?jobid=1#form", "JOB_51"),
        ("https://www.iguopin.com/job/detail?id=123&from=share#apply", "GUOPIN"),
        ("https://mp.weixin.qq.com/s/abc123?scene=1&click_id=2#section", "WECHAT"),
        (
            "https://careersite.tupu360.com/pfizercampus/position/detail?positionId=1",
            "CUSTOM_RECRUITMENT_SYSTEM",
        ),
        ("https://advancy.recruitee.com/", "CUSTOM_RECRUITMENT_SYSTEM"),
        ("https://mh.hire66.com/position?secret_key=abc#apply", "CUSTOM_RECRUITMENT_SYSTEM"),
        ("https://zpks.sun-hrm.com/nindex/?ecode=zhrzp", "CUSTOM_RECRUITMENT_SYSTEM"),
        ("https://nmnshxy2026.hersingdat.com/", "CUSTOM_RECRUITMENT_SYSTEM"),
        (
            "https://ahgzcz.pzhl.net/index.php/reg/signlogin/?EXAMID=9278",
            "CUSTOM_RECRUITMENT_SYSTEM",
        ),
        ("https://c.exam-sp.com/t/gsyfjh", "CUSTOM_RECRUITMENT_SYSTEM"),
        (
            "https://m.izhanchi.com/pages/index/companyDetail?companyid=100526383",
            "CUSTOM_RECRUITMENT_SYSTEM",
        ),
        (
            "https://wscloud.kingdee.com/ws_sync/register/index.html#/recLogin?pageType=myApplication",
            "CUSTOM_RECRUITMENT_SYSTEM",
        ),
        (
            "https://gzw.jiangxi.gov.cn/jxsgzw/rczp/content/content_2080225211822284800.html?from=notice#jobs",
            "GOVERNMENT_NOTICE",
        ),
        ("https://zhaopin.aircas.ac.cn/index", "COMPANY_RECRUITMENT_SITE"),
        ("https://outreach.didichuxing.com/elite/", "COMPANY_RECRUITMENT_SITE"),
        ("https://zhaopin.szgzjg.com", "COMPANY_RECRUITMENT_SITE"),
        ("https://www.lixiang.com/", "COMPANY_WEBSITE"),
        ("https://www.cqrc.net/", "PUBLIC_RECRUITMENT_PORTAL"),
        ("https://pgwxwbkv.jsjform.com/f/PL444i", "FORM_OR_SHORT"),
        ("https://wj.toutiao.com/q/v2/7657509120173735979/975xOc70/4d7d/#/", "FORM_OR_SHORT"),
        ("https://send2me.cn/tzC8ZxNV/QWK3n5q5RD36Cg", "FORM_OR_SHORT"),
        ("https://dqr.cn/oAcdqp/qMFWsxv", "FORM_OR_SHORT"),
        ("mailto:hr@example.com?subject=apply", "EMAIL"),
        ("邮箱投递：hr@example.com", "EMAIL"),
        ("https://jsj.top/f/abc123?source=wechat#form", "FORM_OR_SHORT"),
        ("https://careers.example.com/jobs/123?source=campus#apply", "COMPANY_RECRUITMENT_SITE"),
        ("not a link", "UNKNOWN"),
    ],
)
def test_classify_real_link_shapes(url: str, expected: str) -> None:
    assert classify_link(url) == expected


def test_classification_does_not_change_query_or_fragment() -> None:
    url = "https://app.mokahr.com/job/detail?id=123&source=wechat#apply"
    assert classify_link(url) == "MOKA"
    assert "?id=123&source=wechat#apply" in url
