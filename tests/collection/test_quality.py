from dataclasses import replace
from datetime import UTC, datetime

from jobpicky.collection import pipeline
from jobpicky.collection.link_classification import BEISEN, COMPANY_RECRUITMENT_SITE, WECHAT
from jobpicky.collection.quality import CollectionQualityPolicy, split_table_job_titles
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
    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert len({item.source_job_id for item in result.batch.items}) == 2
    assert all(item.description is None for item in result.batch.items)
    assert all(item.metadata["batch"] == "秋招专场" for item in result.batch.items)
    assert all(
        item.metadata["table_job_summary"] == "后端工程师、前端工程师"
        for item in result.batch.items
    )
    assert all(
        item.apply_url == "https://mp.weixin.qq.com/s/article-1" for item in result.batch.items
    )
    assert all(item.recruitment_type == "校招" for item in result.batch.items)
    assert all(item.metadata["collection_mode"] == "TABLE_FALLBACK" for item in result.batch.items)
    assert all(
        item.metadata["quality_reasons"] == ["PARSER_POLICY_TABLE_FALLBACK"]
        for item in result.batch.items
    )


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

    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert all(
        item.metadata["quality_reasons"] == ["GENERIC_OR_MISSING_TITLE"]
        for item in result.batch.items
    )


def test_multi_job_parser_title_falls_back_to_distinct_table_jobs(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [{"title": "后端工程师、前端工程师", "description": "页面正文"}],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert all(item.metadata["collection_mode"] == "TABLE_FALLBACK" for item in result.batch.items)
    assert all(
        item.metadata["quality_reasons"] == ["MULTI_JOB_TITLE"] for item in result.batch.items
    )


def test_space_separated_parser_title_falls_back_to_distinct_table_jobs(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [{"title": "后端工程师 前端工程师", "description": "页面正文"}],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert all(
        item.metadata["quality_reasons"] == ["MULTI_JOB_TITLE"] for item in result.batch.items
    )


def test_unsafe_delimited_parser_title_is_not_accepted(monkeypatch) -> None:
    monkeypatch.setitem(
        pipeline.PARSERS,
        BEISEN,
        lambda _: [{"title": "岗位名称及任职要求，全部招聘岗位信息", "description": "页面正文"}],
    )
    result = pipeline.run_pipeline(
        "source-1",
        [make_row("https://acme.zhiye.com/campus/jobs")],
        now=NOW,
    )

    assert [item.title for item in result.batch.items] == ["后端工程师", "前端工程师"]
    assert all(
        item.metadata["quality_reasons"] == ["UNSAFE_JOB_TITLE"] for item in result.batch.items
    )


def test_unsafe_table_fallback_is_rejected() -> None:
    row = make_row("https://mp.weixin.qq.com/s/article-1")
    row = replace(
        row, job_directions="岗位名称及任职要求详见公告正文，请点击链接查看全部招聘岗位信息"
    )
    result = pipeline.run_pipeline("source-1", [row], now=NOW)

    assert result.batch.items == []
    assert result.batch.complete is False
    assert result.unsupported[0].reason.startswith("table fallback failed")


def test_table_title_split_supports_categories_and_keeps_parenthetical_text() -> None:
    assert split_table_job_titles("研发技术类 工业设计类 设备技术类 品质技术类 信息技术类") == [
        "研发技术类",
        "工业设计类",
        "设备技术类",
        "品质技术类",
        "信息技术类",
    ]

    assert split_table_job_titles("博士后研究员（研究方向：人工智能；机器人）") == [
        "博士后研究员（研究方向：人工智能；机器人）"
    ]
    assert split_table_job_titles(
        "博士后研究员（基础设施领域：公路/桥梁；智能建造领域：工程装备智能化）"
    ) == ["博士后研究员（基础设施领域：公路/桥梁；智能建造领域：工程装备智能化）"]

    assert split_table_job_titles("AI 应用工程师") == ["AI 应用工程师"]
    assert split_table_job_titles("AI工具开发 intern AI咨询实习生 数字化创新实习生") == [
        "AI工具开发 intern",
        "AI咨询实习生",
        "数字化创新实习生",
    ]
    assert split_table_job_titles("AI 与高性能计算类 硬件类 软件类 机器人和智能驾驶类") == [
        "AI 与高性能计算类",
        "硬件类",
        "软件类",
        "机器人和智能驾驶类",
    ]
    assert split_table_job_titles("管培生岗位：品牌推广 市场营销 研发技术") == [
        "品牌推广",
        "市场营销",
        "研发技术",
    ]


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
