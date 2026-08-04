from pathlib import Path

import pytest

from jobpicky.collection.parsers.moka import _is_open, entry_identity, parse

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
