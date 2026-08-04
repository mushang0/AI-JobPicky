from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.phenom import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_phenom_parser_reads_embedded_public_job_data() -> None:
    page = (FIXTURES / "phenom_job.html").read_text()
    jobs = parse(
        "https://careers.example.test/global/en/job/phenom-job-001/platform", lambda _: page
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "phenom-job-001"
    assert jobs[0]["title"] == "平台研发工程师 - Campus"
    assert jobs[0]["description"] == "负责招聘平台服务建设。 熟悉 Python 或 Go。"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["detail_url"] == (
        "https://careers.example.test/global/en/job/phenom-job-001/platform"
    )
    assert jobs[0]["apply_url"] == "https://apply.example.test/job/phenom-job-001"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "phenom-careers"
    assert metadata["detail_status"] == "embedded_public_data"
    assert metadata["ats"] == "EIGHTFOLD"
    assert jobs[0]["recruitment_type"] == "校招"


def test_phenom_parser_rejects_pages_without_public_job_data() -> None:
    with pytest.raises(ValueError, match="no public job data"):
        parse("https://careers.example.test/global/en/search-results", lambda _: "<html></html>")
