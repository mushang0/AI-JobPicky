from __future__ import annotations

from jobpicky.contracts import CollectedJob
from jobpicky.infrastructure.job_catalog import _identity_key


def test_identity_uses_detail_host_when_legacy_feishu_entries_lack_platform_metadata() -> None:
    jobs = [
        CollectedJob(
            source_id="entry-one",
            company_name="科大讯飞",
            title="AI产品经理－工程平台/方案方向 (J13839)",
            locations=["安徽省·合肥"],
            description="公开 JD",
            source_job_id="d37a1c18-53c6-42ff-b874-eb8aae29bae8",
            metadata={},
            detail_url="https://iflytek.zhaopin.com/jobs/detail?jobAdId=d37a1c18-53c6-42ff-b874-eb8aae29bae8",
        ),
        CollectedJob(
            source_id="entry-two",
            company_name="科大讯飞",
            title="AI产品经理－工程平台/方案方向 (J13839)",
            locations=["安徽省·合肥"],
            description="公开 JD",
            source_job_id="d37a1c18-53c6-42ff-b874-eb8aae29bae8",
            metadata={},
            detail_url="https://iflytek.zhaopin.com/campus/detail?jobAdId=d37a1c18-53c6-42ff-b874-eb8aae29bae8",
        ),
    ]

    assert _identity_key(jobs[0]) == _identity_key(jobs[1])
    platform_jobs = [job.model_copy(update={"metadata": {"platform": "ZHAOPIN"}}) for job in jobs]
    assert _identity_key(platform_jobs[0]) == _identity_key(platform_jobs[1])
    different_host = jobs[1].model_copy(
        update={"detail_url": "https://other.example.com/job/d37a1c18"}
    )
    assert _identity_key(jobs[0]) != _identity_key(different_host)
