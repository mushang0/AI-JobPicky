import csv
from pathlib import Path

from jobpicky.collection.link_classification import BEISEN, classify_link


def test_beisen_sample_has_two_distinct_beisen_sources() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "collection" / "beisen_sample.csv"

    with fixture.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    links = [row["投递链接"] for row in rows]
    assert len(rows) == 2
    assert len(set(links)) == 2
    assert {classify_link(link) for link in links} == {BEISEN}
    assert len({row["公司名称"] for row in rows}) == 2
