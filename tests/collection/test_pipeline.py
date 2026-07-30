from datetime import UTC, datetime

import pytest

from jobpicky.collection import pipeline
from jobpicky.collection.pipeline import (
    merge_job_fields,
    run_pipeline,
    run_pipeline_by_source,
    source_id_for_entry,
)
from jobpicky.collection.spreadsheet import SpreadsheetRow
from jobpicky.contracts import CollectedJob


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


def test_merge_prefers_website_fields_and_uses_detail_as_apply_url() -> None:
    job = merge_job_fields(
        "source-1",
        make_row("https://acme.zhiye.com/campus/jobs"),
        {
            "source_job_id": "job-1",
            "title": "网站真实岗位",
            "description": None,
            "locations": ["网站地点"],
            "detail_url": "https://acme.zhiye.com/job/1",
            "apply_url": None,
            "salary_min": 12000,
            "salary_max": 18000,
            "education_requirement": "硕士",
            "recruitment_type": "社招",
        },
    )

    assert isinstance(job, CollectedJob)
    assert job.title == "网站真实岗位"
    assert job.description is None
    assert job.detail_url == "https://acme.zhiye.com/job/1"
    assert job.apply_url == job.detail_url
    assert job.locations == ["网站地点"]
    assert job.salary_min == 12000
    assert job.education_requirement == "硕士"
    assert job.recruitment_type == "社招"
    assert job.company_name == "表格公司"
    assert job.company_nature == "民企"
    assert job.graduation_years == [2027]
    assert job.metadata["industry"] == "软件"
    assert job.metadata["announcement_url"] == "https://example.com/notice"


def test_table_values_do_not_fill_missing_website_facts() -> None:
    job = merge_job_fields(
        "source-1", make_row("https://acme.zhiye.com/campus/jobs"), {"title": "网站岗位"}
    )

    assert job.locations == ["表格地点"]
    assert job.education_requirement == "本科"
    assert job.recruitment_type == "校招"
    assert job.deadline_at == datetime(2026, 8, 20, tzinfo=UTC)
    assert job.source_ref == "table-row:12"


def test_one_sheet_row_creates_one_collected_job_per_website_job(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        "BEISEN",
        lambda _: [
            {"source_job_id": "1", "title": "后端工程师"},
            {"source_job_id": "2", "title": "前端工程师"},
        ],
    )

    result = run_pipeline("source-1", [make_row("https://acme.zhiye.com/campus/jobs")])

    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert result.batch.complete is True
    assert result.unsupported == []


def test_feishu_link_uses_the_platform_parser(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "parse_feishu",
        lambda _: [{"source_job_id": "feishu-1", "title": "飞书岗位"}],
    )

    result = run_pipeline(
        "source-1",
        [make_row("https://acme.jobs.feishu.cn/531403/position/list")],
    )

    assert [item.source_job_id for item in result.batch.items] == ["feishu-1"]
    assert result.batch.complete is True


def test_unsupported_link_is_recorded_with_row_and_reason() -> None:
    result = run_pipeline("source-1", [make_row("https://app.mokahr.com/campus-recruitment/acme")])

    assert result.batch.items == []
    assert result.batch.complete is False
    assert len(result.unsupported) == 1
    failure = result.unsupported[0]
    assert failure.url.endswith("/acme")
    assert failure.link_type == "MOKA"
    assert failure.row_number == 12
    assert "no parser implemented" in failure.reason


def test_invalid_website_job_is_not_replaced_by_table_direction() -> None:
    with pytest.raises(ValueError, match="without title"):
        merge_job_fields("source-1", make_row("https://acme.zhiye.com/campus/jobs"), {})


def test_recruitment_entries_get_stable_distinct_source_ids(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        "BEISEN",
        lambda _: [{"source_job_id": "1", "title": "后端工程师"}],
    )
    first_url = "https://ACME.zhiye.com/campus/jobs/?b=2&a=1#top"
    equivalent_url = "https://acme.zhiye.com/campus/jobs?a=1&b=2"
    second_url = "https://other.zhiye.com/campus/jobs"

    assert source_id_for_entry("表格公司", first_url) == source_id_for_entry(
        "表格公司", equivalent_url
    )
    assert source_id_for_entry("表格公司", first_url) != source_id_for_entry("另一公司", first_url)

    results = run_pipeline_by_source([make_row(first_url, second_url)])

    assert len(results) == 2
    assert len({result.batch.source_id for result in results}) == 2
    assert all(
        item.source_id == result.batch.source_id
        for result in results
        for item in result.batch.items
    )
