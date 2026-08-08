from pathlib import Path

import pytest

from jobpicky.collection.parsers import didi

FIXTURES = Path(__file__).parent / "fixtures"
DIDI_URL = "https://outreach.didichuxing.com/elite/"


def test_didi_parser_reuses_the_official_moka_source(monkeypatch: pytest.MonkeyPatch) -> None:
    page = (FIXTURES / "didi_page.html").read_text()
    captured: list[str] = []

    def parse_moka(url: str) -> list[dict[str, object]]:
        captured.append(url)
        return [{"source_job_id": "job-1", "title": "算法工程师", "metadata": {}}]

    monkeypatch.setattr(didi, "parse_moka", parse_moka)

    jobs = didi.parse(DIDI_URL, lambda _url: page)

    assert jobs[0]["title"] == "算法工程师"
    assert captured == ["https://app.mokahr.com/campus-recruitment/didiglobal/116021#/jobs"]
    assert jobs[0]["metadata"] == {
        "discovery_route": "didi_official_page_to_moka",
        "discovered_from": DIDI_URL,
    }


def test_didi_parser_rejects_a_page_without_the_official_moka_link() -> None:
    with pytest.raises(ValueError, match="no official Moka campus link"):
        didi.parse(DIDI_URL, lambda _url: "<html><body>招聘说明</body></html>")
