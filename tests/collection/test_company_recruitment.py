import pytest

from jobpicky.collection.parsers import company_recruitment


@pytest.mark.parametrize(
    ("url", "platform_family"),
    [
        ("https://jobs.ecoflow.com/602892/position/list", "feishu-careers"),
        (
            "https://campus.sonoscape.com/campus-recruitment/sonoscape/94392/",
            "moka-careers",
        ),
    ],
)
def test_company_recruitment_dispatches_custom_domains_by_platform(
    monkeypatch: pytest.MonkeyPatch, url: str, platform_family: str
) -> None:
    def parser(_: str) -> list[dict[str, object]]:
        return [{"source_job_id": platform_family, "title": "平台岗位"}]

    monkeypatch.setitem(company_recruitment._PLATFORM_PARSERS, platform_family, parser)

    jobs = company_recruitment.parse(url)

    assert jobs == [{"source_job_id": platform_family, "title": "平台岗位"}]
