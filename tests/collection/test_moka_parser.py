from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.moka import (
    MokaSession,
    _decrypt_detail_response,
    _is_open,
    entry_identity,
    parse,
)

FIXTURE = Path(__file__).parent / "fixtures" / "moka_init_data.html"
LIST_URL = "https://app.mokahr.com/campus-recruitment/demo/12345#/jobs"
DETAIL_URL = "https://app.mokahr.com/m/campus-recruitment/demo/12345#/job/job-open?from=qrcode"


def fixture_html() -> str:
    return FIXTURE.read_text()


def test_moka_parser_reads_server_rendered_job_list() -> None:
    jobs = parse(LIST_URL, lambda _url: fixture_html())

    assert [job["source_job_id"] for job in jobs] == ["job-open"]
    assert jobs[0]["title"] == "算法工程师"
    assert jobs[0]["locations"] == ["北京"]
    assert jobs[0]["recruitment_type"] == "校招"
    published_at = jobs[0]["published_at"]
    assert hasattr(published_at, "year")
    assert published_at.year == 2026
    metadata = jobs[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["department"] == "研发部"


def test_moka_parser_collects_all_public_list_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    first_page = [
        {
            "id": f"job-{index}",
            "title": f"岗位 {index}",
            "status": "open",
            "jobDescription": f"<p>职责 {index}</p>",
        }
        for index in range(30)
    ]
    second_page = [
        {
            "id": "job-30",
            "title": "岗位 30",
            "status": "open",
            "jobDescription": "<p>职责 30</p>",
        }
    ]
    offsets: list[int] = []

    def fetch_page(_: MokaSession, url: str) -> tuple[str, str]:
        return url, fixture_html()

    def fetch_job_list(
        _: MokaSession,
        _page_url: str,
        mode: str,
        org_id: str,
        site_id: str,
        locale: str,
        limit: int,
        offset: int,
        _aes_iv: str | None,
    ) -> dict[str, object]:
        assert (mode, org_id, site_id, locale, limit) == (
            "campus-recruitment",
            "demo",
            "12345",
            "zh-CN",
            30,
        )
        offsets.append(offset)
        return {
            "jobStats": {"orgId": "demo", "total": 31},
            "jobs": first_page if offset == 0 else second_page,
        }

    monkeypatch.setattr(MokaSession, "fetch_page", fetch_page)
    monkeypatch.setattr(MokaSession, "fetch_job_list", fetch_job_list)

    jobs = parse(LIST_URL)

    assert len(jobs) == 31
    assert offsets == [0, 30]
    assert jobs[-1]["source_job_id"] == "job-30"
    assert jobs[-1]["description"] == "职责 30"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "list-api"
    assert metadata["list_count"] == 31


def test_moka_parser_fetches_direct_job_outside_initial_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail_url = LIST_URL.replace("#/jobs", "#/job/job-page-2")

    def fetch_page(_: MokaSession, url: str) -> tuple[str, str]:
        return url, fixture_html()

    def fetch_job_detail(
        _: MokaSession,
        _page_url: str,
        _org_id: str,
        _site_id: str,
        job_id: str,
        _locale: str,
        _aes_iv: str | None,
    ) -> dict[str, object]:
        assert job_id == "job-page-2"
        return {
            "id": job_id,
            "title": "第二页岗位",
            "status": "open",
            "jobDescription": "<p>第二页 JD</p>",
        }

    monkeypatch.setattr(MokaSession, "fetch_page", fetch_page)
    monkeypatch.setattr(MokaSession, "fetch_job_detail", fetch_job_detail)

    jobs = parse(detail_url)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "job-page-2"
    assert jobs[0]["description"] == "第二页 JD"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "api"


def test_moka_detail_url_drops_tracking_tokens() -> None:
    url = (
        "https://app.mokahr.com/campus-recruitment/demo/12345?"
        "sourceToken=redacted&locale=zh-CN#/job/job-open"
    )

    jobs = parse(url, lambda _url: fixture_html())

    assert jobs[0]["detail_url"] == (
        "https://app.mokahr.com/campus-recruitment/demo/12345?locale=zh-CN#/job/job-open"
    )


def test_moka_parser_fetches_and_normalises_job_detail() -> None:
    calls: list[tuple[str, str, str, str, str]] = []

    def fetch_detail(
        page_url: str,
        org_id: str,
        site_id: str,
        job_id: str,
        locale: str,
    ) -> dict[str, object]:
        calls.append((page_url, org_id, site_id, job_id, locale))
        return {"jobDescription": "<p>岗位职责</p><p>熟悉 Python &amp; Go。</p>"}

    jobs = parse(LIST_URL, lambda _url: fixture_html(), fetch_detail)

    assert jobs[0]["description"] == "岗位职责\n熟悉 Python & Go。"
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "api"
    assert calls == [(LIST_URL, "demo", "12345", "job-open", "zh-CN")]


def test_moka_detail_response_is_decrypted() -> None:
    detail = _decrypt_detail_response(
        {
            "data": (
                "1THXlBikAEAVg9cIxBZPcbRoa1FVgptyGySnWh7POUbvR3UFKO/KG6RYVv2FEt95"
                "AVzen/mUfiQ74OXz1zc7QXD2wxohpPd9hLLkwFDl9K5gr/IAFbGrEBY46oL0/q8R5Y6"
                "ZD0mYrJHUzvASlPofA1rmAwOWK6KLvhTbnySTrpOTBEHzlwfU6CY6V/D9Ejco"
            ),
            "necromancer": "1234567890abcdef",
        },
        "abcdef1234567890",
    )

    assert detail["jobDescription"] == "<p>岗位职责</p><p>熟悉 Python &amp; Go。</p>"


def test_moka_parser_keeps_job_when_detail_fetch_fails() -> None:
    def fetch_detail(*_args: str) -> dict[str, object]:
        raise TimeoutError("detail request timed out")

    jobs = parse(LIST_URL, lambda _url: fixture_html(), fetch_detail)

    assert jobs[0]["description"] is None
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "failed"
    assert metadata["detail_error_type"] == "TimeoutError"


@pytest.mark.parametrize(
    "url",
    [
        "https://campus.sonoscape.com/campus-recruitment/sonoscape/94392/#/jobs",
        "https://campus.fingard.com/campus_apply/baorong/25901/#/jobs",
    ],
)
def test_moka_parser_accepts_verified_custom_domain_routes(url: str) -> None:
    jobs = parse(url, lambda _url: fixture_html())

    assert jobs[0]["source_job_id"] == "job-open"


def test_moka_parser_filters_a_direct_job_from_fragment() -> None:
    jobs = parse(DETAIL_URL, lambda _url: fixture_html())

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "job-open"
    detail_url = jobs[0]["detail_url"]
    assert isinstance(detail_url, str)
    assert "/job/job-open" in detail_url


def test_moka_parser_rejects_closed_or_missing_direct_job() -> None:
    closed_url = LIST_URL.replace("#/jobs", "#/job/job-closed")
    with pytest.raises(ValueError, match="closed or absent"):
        parse(closed_url, lambda _url: fixture_html())


def test_moka_parser_accepts_a_reopened_open_job() -> None:
    assert _is_open(
        {
            "status": "open",
            "closedAt": "2026-05-09T21:30:12.000Z",
            "openedAt": "2026-05-10T16:00:00.000Z",
        }
    )


def test_moka_entry_identity_ignores_list_tracking_state() -> None:
    first = "https://app.mokahr.com/campus-recruitment/ti/143986?sourceToken=one#/"
    second = "https://app.mokahr.com/campus-recruitment/ti/143986?sourceToken=two#/jobs"
    direct = "https://app.mokahr.com/campus-recruitment/ti/143986#/job/job-1"

    assert entry_identity(first) == entry_identity(second)
    assert entry_identity(direct) != entry_identity(first)


def test_moka_parser_requires_init_data() -> None:
    with pytest.raises(ValueError, match="no init-data"):
        parse(LIST_URL, lambda _url: "<html></html>")
