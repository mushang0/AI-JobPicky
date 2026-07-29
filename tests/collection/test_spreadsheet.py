from jobpicky.collection.spreadsheet import extract_links, extract_row, rows_from_values


def test_spreadsheet_links_do_not_duplicate_mailto_email() -> None:
    assert extract_links("mailto:hr@example.com") == ["mailto:hr@example.com"]


def test_fixed_sheet_fields_are_extracted_without_splitting_job_directions() -> None:
    row = extract_row(
        7,
        [
            "2026/07/27",
            "示例公司",
            "民企",
            "软件",
            "后端, 前端, 测试",
            "北京, 上海",
            "2026-08-20",
            "2027届, 2028届",
            "本科",
            "秋招专场",
            "示例公告",
            "https://example.com/notice",
            "https://acme.zhiye.com/campus/jobs",
            "计算机相关专业",
            "有笔试",
        ],
    )

    assert row is not None
    assert row.row_number == 7
    assert row.updated_at is not None
    assert row.company_name == "示例公司"
    assert row.job_directions == "后端, 前端, 测试"
    assert row.apply_links == ["https://acme.zhiye.com/campus/jobs"]
    assert row.graduation_years == [2027, 2028]
    assert row.recruitment_type == "校招"


def test_fixed_sheet_ignores_instruction_rows_and_slash_placeholders() -> None:
    rows = rows_from_values(
        [
            ["", "（必看）表格使用说明", "", "", "", "", "", "", "", ""],
            [
                "",
                "示例公司",
                "民企",
                "软件",
                "后端,前端",
                "北京",
                "尽快投递",
                "2027届",
                "本科",
                "秋招",
                "",
                "",
                "/",
            ],
        ]
    )

    assert len(rows) == 1
    assert rows[0].apply_links == []
