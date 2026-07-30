from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from .pipeline import PipelineResult, UnsupportedLink


@dataclass(frozen=True)
class ParserGap:
    platform: str
    domain: str
    failure_type: str
    reason: str
    count: int
    companies: list[str]
    samples: list[dict[str, object]]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _failure_type(reason: str) -> str:
    if "job is closed" in reason:
        return "CLOSED"
    if reason.startswith("no parser implemented"):
        return "UNSUPPORTED"
    if reason.startswith("parser failed"):
        return "PARSER_ERROR"
    if reason == "parser returned no jobs":
        return "EMPTY_RESULT"
    if reason.startswith("job fields invalid"):
        return "INVALID_JOB"
    return "OTHER"


def aggregate_parser_gaps(
    failures: Iterable[UnsupportedLink], *, sample_limit: int = 3
) -> list[ParserGap]:
    groups: dict[tuple[str, str, str, str], list[UnsupportedLink]] = defaultdict(list)
    for failure in failures:
        domain = (urlsplit(failure.url).hostname or "").lower()
        kind = _failure_type(failure.reason)
        groups[(failure.link_type, domain, kind, failure.reason)].append(failure)

    gaps = []
    for (platform, domain, kind, reason), items in groups.items():
        gaps.append(
            ParserGap(
                platform=platform,
                domain=domain,
                failure_type=kind,
                reason=reason,
                count=len(items),
                companies=sorted(
                    {item.company_name for item in items if item.company_name is not None}
                ),
                samples=[
                    {"url": item.url, "row_number": item.row_number}
                    for item in items[: max(sample_limit, 0)]
                ],
            )
        )
    return sorted(gaps, key=lambda gap: (-gap.count, gap.platform, gap.domain, gap.reason))


def gaps_from_results(
    results: Iterable[PipelineResult], *, sample_limit: int = 3
) -> list[ParserGap]:
    return aggregate_parser_gaps(
        (failure for result in results for failure in result.unsupported),
        sample_limit=sample_limit,
    )


__all__ = ["ParserGap", "aggregate_parser_gaps", "gaps_from_results"]
