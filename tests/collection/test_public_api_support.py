import pytest

from jobpicky.collection.parsers.public_api_support import PublicPage, collect_pages


def test_collect_pages_deduplicates_and_stops_at_reported_total() -> None:
    pages = {
        1: PublicPage(3, [{"id": "job-1"}, {"id": "job-2"}], page_count=2),
        2: PublicPage(3, [{"id": "job-2"}, {"id": "job-3"}], page_count=2),
    }
    calls: list[int] = []

    def fetch_page(page: int) -> PublicPage:
        calls.append(page)
        return pages[page]

    items, total = collect_pages(
        fetch_page,
        source="test",
        max_jobs=10,
        max_pages=2,
        job_id=lambda item: str(item["id"]),
    )

    assert [item["id"] for item in items] == ["job-1", "job-2", "job-3"]
    assert total == 3
    assert calls == [1, 2]


def test_collect_pages_rejects_an_incomplete_reported_page() -> None:
    with pytest.raises(ValueError, match="returned 1 of 2 jobs"):
        collect_pages(
            lambda _page: PublicPage(2, [{"id": "job-1"}], page_count=1),
            source="test",
            max_jobs=10,
            max_pages=2,
            job_id=lambda item: str(item["id"]),
        )
