from datetime import UTC, datetime

from jobpicky.collection import pipeline
from jobpicky.collection.link_classification import BEISEN, COMPANY_RECRUITMENT_SITE, WECHAT
from jobpicky.collection.quality import CollectionQualityPolicy
from jobpicky.collection.spreadsheet import SpreadsheetRow


def make_row(*links: str, deadline: datetime | None = None) -> SpreadsheetRow:
    return SpreadsheetRow(
        row_number=7,
        updated_at=None,
        company_name="表格公司",
        company_nature="民企",
        industry="软件",
        job_directions="后端工程师、前端工程师",
        locations=["上海"],
        deadline_at=deadline,
        graduation_years=[2027],
        education_requirement="本科",
        batch="秋招专场",
        announcement_source=None,
        announcement_url=None,
        apply_links=list(links),
        major_requirement=None,
        has_written_test=None,
    )


NOW = datetime(2026, 7, 31, tzinfo=UTC)


def test_known_bad_platform_falls_back_without_calling_parser(monkeypatch) -> None:
    called = False

    def parser(_: str) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return [{"title": "错误岗位"}]

    monkeypatch.setitem(pipeline.PARSERS, WECHAT, parser)
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://mp.weixin.qq.com/s/article-1")],
        now=NOW,
    )

    assert called is False
    assert result.skipped == []
    assert len(result.batch.items) == 1
    item = result.batch.items[0]
    assert item.title == "后端工程师、前端工程师"
    assert item.description == item.title
    assert item.apply_url == "https://mp.weixin.qq.com/s/article-1"
    assert item.recruitment_type == "校招"
    assert item.metadata["collection_mode"] == "TABLE_FALLBACK"
    assert item.metadata["quality_reasons"] == ["PARSER_POLICY_TABLE_FALLBACK"]


def test_company_recruitment_parser_is_attempted_before_fallback(monkeypatch) -> None:
    called = False

    def parser(_: str) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return [{"source_job_id": "job-1", "title": "真实岗位", "description": "公开 JD"}]

    monkeypatch.setitem(pipeline.PARSERS, COMPANY_RECRUITMENT_SITE, parser)
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://jobs.ecoflow.com/602892/position/list")],
        now=NOW,
    )

    assert called is True
    assert result.unsupported == []
    assert result.batch.items[0].title == "真实岗位"
    assert result.batch.items[0].metadata["collection_mode"] == "PARSED"


def test_bad_parsed_title_falls_back_to_table(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [{"title": "职位详情", "description": "页面正文"}],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert len(result.batch.items) == 1
    assert result.batch.items[0].title == "后端工程师、前端工程师"
    assert result.batch.items[0].metadata["quality_reasons"] == ["GENERIC_OR_MISSING_TITLE"]


def test_page_titles_and_announcements_fall_back_to_table(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [
            {
                "title": "二维码",
                "metadata": {"record_kind": "public_announcement"},
            }
        ],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert result.batch.items[0].metadata["collection_mode"] == "TABLE_FALLBACK"
    assert result.batch.items[0].metadata["quality_reasons"] == [
        "ANNOUNCEMENT_NOT_JOB",
        "GENERIC_OR_MISSING_TITLE",
    ]


def test_reliable_parser_keeps_facts_but_table_type_wins(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [
            {
                "source_job_id": "job-1",
                "title": "网站真实岗位",
                "description": "网站真实 JD",
                "recruitment_type": "社招",
            }
        ],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    item = result.batch.items[0]
    assert item.title == "网站真实岗位"
    assert item.description == "网站真实 JD"
    assert item.recruitment_type == "校招"
    assert item.metadata["collection_mode"] == "PARSED"
    assert item.metadata["quality_reasons"] == ["RECRUITMENT_TYPE_CONFLICT"]


def test_expired_row_is_skipped_before_parser(monkeypatch) -> None:
    called = False

    def parser(_: str) -> list[dict[str, object]]:
        nonlocal called
        called = True
        return [{"title": "不应执行"}]

    monkeypatch.setitem(pipeline.PARSERS, BEISEN, parser)
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs", deadline=datetime(2026, 7, 1, tzinfo=UTC))],
        now=NOW,
    )

    assert called is False
    assert result.batch.items == []
    assert len(result.skipped) == 1
    assert result.skipped[0].reason == "STALE_DEADLINE"


def test_old_published_parser_result_is_skipped(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [{"title": "旧岗位", "published_at": datetime(2024, 1, 1, tzinfo=UTC)}],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert result.batch.items == []
    assert result.skipped[0].reason == "STALE_PUBLISHED_AT"


def test_stale_threshold_can_be_overridden() -> None:
    policy = CollectionQualityPolicy(published_stale_days_by_type={"校招": 1})
    assert policy.stale_days_for("校招") == 1
