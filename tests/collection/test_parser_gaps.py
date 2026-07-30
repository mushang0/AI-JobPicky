from jobpicky.collection.parser_gaps import aggregate_parser_gaps
from jobpicky.collection.pipeline import UnsupportedLink


def test_parser_gaps_group_failures_and_limit_samples() -> None:
    failures = [
        UnsupportedLink(
            url=f"https://app.mokahr.com/campus/acme/{number}",
            link_type="MOKA",
            row_number=number,
            reason="no parser implemented for link type MOKA",
            company_name="示例公司",
        )
        for number in range(1, 4)
    ]

    gaps = aggregate_parser_gaps(failures, sample_limit=2)

    assert len(gaps) == 1
    assert gaps[0].platform == "MOKA"
    assert gaps[0].domain == "app.mokahr.com"
    assert gaps[0].failure_type == "UNSUPPORTED"
    assert gaps[0].count == 3
    assert gaps[0].companies == ["示例公司"]
    assert len(gaps[0].samples) == 2
