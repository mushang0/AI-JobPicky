from pathlib import Path

import pytest

from jobpicky.collection.parsers import zte

FIXTURES = Path(__file__).parent / "fixtures"
ZTE_URL = "https://job.zte.com.cn/cn/campus-recruitment/Recruitment_positions/freshstudent.html"


def test_zte_parser_reuses_the_unfiltered_official_moka_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = (FIXTURES / "zte_page.html").read_text()
    captured: list[str] = []

    def parse_moka(url: str) -> list[dict[str, object]]:
        captured.append(url)
        return [{"source_job_id": "job-1", "title": "软件开发工程师", "metadata": {}}]

    monkeypatch.setattr(zte, "parse_moka", parse_moka)

    jobs = zte.parse(ZTE_URL, lambda _url: page)

    assert jobs[0]["title"] == "软件开发工程师"
    assert captured == ["https://app.mokahr.com/campus-recruitment/zte/46903#/jobs"]
    assert jobs[0]["metadata"] == {
        "discovery_route": "zte_official_page_to_moka",
        "discovered_from": ZTE_URL,
    }


def test_zte_parser_rejects_a_page_without_the_official_moka_link() -> None:
    with pytest.raises(ValueError, match="no official Moka campus link"):
        zte.parse(ZTE_URL, lambda _url: "<html><body>招聘说明</body></html>")
