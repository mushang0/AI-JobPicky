from __future__ import annotations

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from jobpicky.collection import feishu_bitable
from jobpicky.collection.feishu_bitable import (
    FeishuBitableClient,
    FeishuBitableConfig,
    FeishuBitableSource,
    FeishuRecord,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._raw = json.dumps(payload).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._raw


def _record(*, updated_at: object = "2026-06-21") -> FeishuRecord:
    return FeishuRecord(
        record_id="rec-job-1",
        fields={
            "更新时间": updated_at,
            "公司名称": "示例公司",
            "企业性质": "民企",
            "行业分类": "软件",
            "招聘岗位": "后端开发",
            "工作地点": ["北京", "上海"],
            "截止时间": "2026-08-20",
            "届次": "2027届",
            "学历要求": "本科",
            "批次": "秋招",
            "公告来源": "官网",
            "公告链接": {"text": "公告", "link": "https://example.com/notice"},
            "投递链接": {"text": "立即投递", "link": "https://acme.zhiye.com/campus/jobs"},
            "专业要求": "计算机相关专业",
            "是否笔试": "有笔试",
        },
        last_modified_time=datetime(2026, 6, 21, tzinfo=UTC),
    )


def test_bitable_record_is_converted_to_existing_spreadsheet_row() -> None:
    source = FeishuBitableSource(
        FeishuBitableConfig(
            app_token="app-token",
            table_id="tbl-test",
            view_id="view-test",
            since_date=date(2026, 6, 20),
        )
    )

    row = source.row_from_record(_record(), row_number=3)

    assert row is not None
    assert row.source_record_id == "rec-job-1"
    assert row.company_name == "示例公司"
    assert row.locations == ["北京", "上海"]
    assert row.announcement_url == "https://example.com/notice"
    assert row.apply_links == ["https://acme.zhiye.com/campus/jobs"]
    assert source.row_is_after_cutoff(row)


def test_bitable_cutoff_is_strictly_after_configured_date() -> None:
    source = FeishuBitableSource(
        FeishuBitableConfig(
            app_token="app-token",
            table_id="tbl-test",
            view_id=None,
            since_date=date(2026, 6, 20),
        )
    )

    row = source.row_from_record(_record(updated_at="2026-06-20"), row_number=3)

    assert row is not None
    assert not source.row_is_after_cutoff(row)


def test_bitable_source_detects_the_scan_boundary() -> None:
    source = FeishuBitableSource(
        FeishuBitableConfig(
            app_token="app-token",
            table_id="tbl-test",
            view_id=None,
            since_date=date(2026, 6, 20),
        )
    )

    assert source.record_is_at_or_before_cutoff(_record(updated_at="2026-06-20"))
    assert not source.record_is_at_or_before_cutoff(_record(updated_at="2026-06-21"))


def test_bitable_date_timestamp_uses_shanghai_calendar_date() -> None:
    source = FeishuBitableSource(
        FeishuBitableConfig(
            app_token="app-token",
            table_id="tbl-test",
            view_id=None,
            since_date=date(2026, 6, 20),
        )
    )
    timestamp = int(datetime(2026, 6, 21, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)

    row = source.row_from_record(_record(updated_at=timestamp), row_number=3)

    assert row is not None
    assert row.updated_at is not None
    assert row.updated_at.date() == date(2026, 6, 21)
    assert source.row_is_after_cutoff(row)


def test_record_hash_does_not_depend_on_field_order() -> None:
    first = FeishuRecord("rec-1", {"a": 1, "b": ["x", "y"]}, None)
    second = FeishuRecord("rec-1", {"b": ["x", "y"], "a": 1}, None)

    assert FeishuBitableSource.record_hash(first) == FeishuBitableSource.record_hash(second)


def test_iter_records_follows_page_tokens(monkeypatch) -> None:
    responses = iter(
        [
            {
                "code": 0,
                "data": {
                    "items": [{"record_id": "rec-1", "fields": {"公司名称": "甲"}}],
                    "has_more": True,
                    "page_token": "next-page",
                },
            },
            {
                "code": 0,
                "data": {
                    "items": [{"record_id": "rec-2", "fields": {"公司名称": "乙"}}],
                    "has_more": False,
                },
            },
        ]
    )

    def fake_urlopen(*_args: object, **_kwargs: object) -> _Response:
        return _Response(next(responses))

    monkeypatch.setattr(feishu_bitable, "urlopen", fake_urlopen)

    records = list(
        FeishuBitableClient("access-token", retries=1).iter_records(
            "app-token", "tbl-test", page_size=1
        )
    )

    assert [record.record_id for record in records] == ["rec-1", "rec-2"]


def test_iter_records_sends_explicit_sort(monkeypatch) -> None:
    request_bodies: list[dict[str, object]] = []

    def fake_urlopen(request, **_kwargs: object) -> _Response:
        assert request.data is not None
        request_bodies.append(json.loads(request.data.decode()))
        return _Response(
            {
                "code": 0,
                "data": {
                    "items": [],
                    "has_more": False,
                },
            }
        )

    monkeypatch.setattr(feishu_bitable, "urlopen", fake_urlopen)

    list(
        FeishuBitableClient("access-token", retries=1).iter_records(
            "app-token",
            "tbl-test",
            view_id="view-test",
            sort=[{"field_name": "更新时间", "desc": True}],
        )
    )

    assert request_bodies == [
        {
            "automatic_fields": True,
            "sort": [{"field_name": "更新时间", "desc": True}],
            "view_id": "view-test",
        }
    ]
