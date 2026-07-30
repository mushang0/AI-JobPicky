"""Verify one registered platform from a recruitment sheet without database writes."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path

from jobpicky.collection.link_classification import classify_link
from jobpicky.collection.pipeline import PARSERS, merge_job_fields
from jobpicky.collection.spreadsheet import SpreadsheetRow, extract_links, extract_row
from jobpicky.contracts import CollectedJob


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _select_rows(path: Path, platform: str, limit: int) -> tuple[list[str], list[SpreadsheetRow]]:
    selected: list[SpreadsheetRow] = []
    selected_links: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader)
        for row_number, values in enumerate(reader, start=2):
            if len(values) <= 12:
                continue
            for link in extract_links(values[12]):
                if classify_link(link) != platform or link in selected_links:
                    continue
                row_values = list(values)
                row_values[12] = link
                row = extract_row(row_number, row_values)
                if row is not None:
                    selected.append(row)
                    selected_links.add(link)
                if limit > 0 and len(selected) >= limit:
                    return header, selected
    return header, selected


def _write_sample(path: Path, header: Sequence[str], rows: Sequence[SpreadsheetRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header[:15])
        for row in rows:
            writer.writerow(
                [
                    row.updated_at.isoformat() if row.updated_at else "",
                    row.company_name or "",
                    row.company_nature or "",
                    row.industry or "",
                    row.job_directions or "",
                    ", ".join(row.locations),
                    row.deadline_at.date().isoformat() if row.deadline_at else "",
                    ", ".join(f"{year}届" for year in row.graduation_years),
                    row.education_requirement or "",
                    row.batch or "",
                    row.announcement_source or "",
                    row.announcement_url or "",
                    row.apply_links[0],
                    row.major_requirement or "",
                    row.has_written_test or "",
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--platform", required=True, type=str.upper)
    parser.add_argument("--limit", type=int, default=0, help="0 means all matching links")
    args = parser.parse_args()
    if args.limit < 0:
        raise ValueError("--limit must be non-negative")
    platform_parser = PARSERS.get(args.platform)
    if platform_parser is None:
        raise ValueError(f"no registered parser for {args.platform}")

    args.output.mkdir(parents=True, exist_ok=True)
    header, rows = _select_rows(args.input, args.platform, args.limit)
    _write_sample(args.output / "sample.csv", header, rows)

    cases: list[dict[str, object]] = []
    merged_jobs: list[CollectedJob] = []
    review_rows: list[dict[str, object]] = []
    parsed_job_count = 0
    for index, row in enumerate(rows, start=1):
        case_id = f"case-{index:03d}"
        url = row.apply_links[0]
        errors: list[str] = []
        parsed_jobs: list[dict[str, object]] = []
        jobs: list[CollectedJob] = []
        try:
            parsed_jobs = [dict(job) for job in platform_parser(url)]
            if not parsed_jobs:
                raise ValueError("parser returned no verified job title")
            source_id = f"test-source-{args.platform.lower()}"
            jobs = [merge_job_fields(source_id, row, job) for job in parsed_jobs]
        except Exception as exc:  # noqa: BLE001 - preserve the real verification failure
            errors.append(f"{type(exc).__name__}: {exc}")
        parsed_job_count += len(parsed_jobs)
        merged_jobs.extend(jobs)
        case: dict[str, object] = {
            "table_data": {
                "row_number": row.row_number,
                "company_name": row.company_name,
                "job_summary": row.job_directions,
                "locations": row.locations,
                "source_url": url,
            },
            "route": {"link_type": classify_link(url), "parser": args.platform},
            "parsed_jobs": parsed_jobs,
            "merged_jobs": [job.model_dump(mode="json") for job in jobs],
            "validation": {
                "parsed_job_count": len(parsed_jobs),
                "schema_valid": bool(jobs),
                "errors": errors,
            },
        }
        cases.append(case)
        _write_json(args.output / f"{case_id}.json", case)
        review_rows.extend(
            {
                "case_id": case_id,
                "table_row_number": row.row_number,
                "company_name": job.company_name,
                "source_job_id": job.source_job_id,
                "title": job.title,
                "locations": "|".join(job.locations),
                "description_length": len(job.description or ""),
                "detail_url": job.detail_url,
                "schema_valid": True,
                "manual_result": "PENDING",
                "manual_note": "",
            }
            for job in jobs
        )

    summary = {
        "selected_source_count": len(rows),
        "successful_source_count": sum(bool(case["merged_jobs"]) for case in cases),
        "failed_source_count": sum(not case["merged_jobs"] for case in cases),
        "parsed_job_count": parsed_job_count,
        "merged_job_count": len(merged_jobs),
        "schema_valid_count": len(merged_jobs),
        "platform": args.platform,
        "cases": [
            {
                "case_id": f"case-{index:03d}",
                "row_number": row.row_number,
                "url": row.apply_links[0],
            }
            for index, row in enumerate(rows, start=1)
        ],
    }
    _write_json(
        args.output / "merged_jobs.json",
        [job.model_dump(mode="json") for job in merged_jobs],
    )
    _write_json(args.output / "summary.json", summary)
    with (args.output / "review.csv").open("w", encoding="utf-8", newline="") as file:
        fieldnames = list(review_rows[0]) if review_rows else ["case_id"]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "cases"},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
