"""Verify Beisen links without writing to the database."""

from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from jobpicky.collection.link_classification import BEISEN, classify_link
from jobpicky.collection.parsers.beisen import fetch_html
from jobpicky.collection.parsers.beisen import parse as parse_beisen
from jobpicky.collection.pipeline import PARSERS, merge_job_fields
from jobpicky.collection.spreadsheet import SpreadsheetRow, extract_links, extract_row
from jobpicky.contracts import CollectedJob


def _json_default(value: object) -> str:
    return str(value)


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _table_data(row: SpreadsheetRow) -> dict[str, object]:
    return {
        "row_number": row.row_number,
        "company_name": row.company_name,
        "company_nature": row.company_nature,
        "industry": row.industry,
        "job_summary": row.job_directions,
        "location_summary": row.locations,
        "deadline_at": row.deadline_at.isoformat() if row.deadline_at else None,
        "graduation_years": row.graduation_years,
        "education_requirement": row.education_requirement,
        "recruitment_type": row.recruitment_type,
        "announcement_url": row.announcement_url,
        "apply_url": row.apply_links[0] if row.apply_links else None,
    }


def _select_rows(
    path: Path, limit: int, start_row: int, max_row: int | None
) -> tuple[list[str], list[SpreadsheetRow]]:
    selected_links: list[str] = []
    selected_rows: list[SpreadsheetRow] = []

    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader, None)
        if header is None:
            raise ValueError("input CSV is empty")
        for row_number, values in enumerate(reader, start=2):
            if row_number < start_row:
                continue
            if max_row is not None and row_number > max_row:
                break
            if len(values) <= 12:
                continue
            for link in extract_links(values[12]):
                if classify_link(link) != BEISEN or link in selected_links:
                    continue
                row_values = list(values)
                row_values[12] = link
                row = extract_row(row_number, row_values)
                if row is None:
                    continue
                selected_rows.append(row)
                selected_links.append(link)
                if limit > 0 and len(selected_rows) >= limit:
                    break
            if limit > 0 and len(selected_rows) >= limit:
                break

    if limit > 0 and len(selected_rows) < limit:
        raise RuntimeError(f"found only {len(selected_rows)} usable BEISEN rows, need {limit}")
    return header, selected_rows


def _write_sample(path: Path, header: Sequence[str], rows: Sequence[SpreadsheetRow]) -> None:
    # The selected CSV is deliberately a compact review input, not a copy of the source table.
    path.parent.mkdir(parents=True, exist_ok=True)
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
                    row.apply_links[0] if row.apply_links else "",
                    row.major_requirement or "",
                    row.has_written_test or "",
                ]
            )


def _review_rows(
    case_id: str, row: SpreadsheetRow, jobs: Sequence[CollectedJob]
) -> list[dict[str, object]]:
    return [
        {
            "case_id": case_id,
            "table_row_number": row.row_number,
            "company_name": job.company_name,
            "source_url": row.apply_links[0] if row.apply_links else None,
            "source_job_id": job.source_job_id,
            "title": job.title,
            "locations": "|".join(job.locations),
            "detail_url": job.detail_url,
            "description_length": len(job.description or ""),
            "schema_valid": True,
            "manual_result": "PENDING",
            "manual_note": "",
        }
        for job in jobs
    ]


def _run_case(
    case_id: str, row: SpreadsheetRow, output_dir: Path
) -> tuple[dict[str, object], list[CollectedJob]]:
    url = row.apply_links[0]
    link_type = classify_link(url)
    case_dir = output_dir / "raw" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)

    case: dict[str, object] = {
        "table_data": _table_data(row),
        "route": {"link_type": link_type, "parser": "parse_beisen"},
        "parsed_jobs": [],
        "merged_jobs": [],
        "validation": {
            "route_correct": link_type == BEISEN and BEISEN in PARSERS,
            "parsed_job_count": 0,
            "collected_job_valid": False,
            "errors": [],
        },
    }
    errors: list[str] = []
    jobs: list[CollectedJob] = []

    try:

        def fetch_and_save(fetch_url: str) -> str:
            html = fetch_html(fetch_url)
            endpoint = urlsplit(fetch_url).path.rsplit("/", 1)[-1]
            filename = (
                "listing.json"
                if endpoint == "_SearchJobAd"
                else f"detail-{len(list(case_dir.iterdir())):03d}.json"
            )
            (case_dir / filename).write_text(html, encoding="utf-8")
            return html

        parsed_jobs = parse_beisen(url, fetch=fetch_and_save)
        case["parsed_jobs"] = parsed_jobs
        case["validation"]["parsed_job_count"] = len(parsed_jobs)  # type: ignore[index]
        if not parsed_jobs:
            raise ValueError("parser returned no jobs")
        for parsed_job in parsed_jobs:
            jobs.append(merge_job_fields("test-source-001", row, parsed_job))
        case["merged_jobs"] = [job.model_dump(mode="json") for job in jobs]
        case["validation"]["collected_job_valid"] = bool(jobs) and all(  # type: ignore[index]
            CollectedJob.model_validate(job.model_dump()) is not None for job in jobs
        )
    except Exception as exc:  # noqa: BLE001 - the review file must preserve the real failure
        errors.append(f"{type(exc).__name__}: {exc}")
    case["validation"]["errors"] = errors  # type: ignore[index]
    return case, jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", "--sample", dest="input", required=True, type=Path)
    parser.add_argument(
        "--limit",
        type=int,
        default=2,
        help="maximum number of Beisen links; 0 means all links in the scan range",
    )
    parser.add_argument(
        "--start-row",
        type=int,
        default=2,
        help="start scanning at this physical CSV row number (default: 2)",
    )
    parser.add_argument(
        "--max-row",
        type=int,
        default=None,
        help="stop at this physical CSV row number (inclusive)",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.limit < 0:
        raise ValueError("--limit must be non-negative")
    if args.start_row < 2:
        raise ValueError("--start-row must be at least 2")
    if args.max_row is not None and args.max_row < args.start_row:
        raise ValueError("--max-row must be at least --start-row")

    args.output.mkdir(parents=True, exist_ok=True)
    header, rows = _select_rows(args.input, args.limit, args.start_row, args.max_row)
    _write_sample(args.output / "sample.csv", header, rows)

    cases: list[dict[str, object]] = []
    all_jobs: list[CollectedJob] = []
    review_rows: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        case_id = f"case-{index:03d}"
        case, jobs = _run_case(case_id, row, args.output)
        cases.append(case)
        all_jobs.extend(jobs)
        review_rows.extend(_review_rows(case_id, row, jobs))
        _write_json(args.output / f"{case_id}.json", case)

    source_successes = sum(bool(case["merged_jobs"]) for case in cases)
    ids = [job.source_job_id or job.detail_url for job in all_jobs]
    duplicate_count = len(ids) - len(set(ids))
    summary = {
        "selected_source_count": len(rows),
        "successful_source_count": source_successes,
        "failed_source_count": len(rows) - source_successes,
        "parsed_job_count": sum(case["validation"]["parsed_job_count"] for case in cases),
        "merged_job_count": len(all_jobs),
        "schema_valid_count": len(all_jobs),
        "schema_invalid_count": 0,
        "duplicate_job_count": duplicate_count,
        "cases": [
            {
                "case_id": f"case-{index:03d}",
                "row_number": row.row_number,
                "url": row.apply_links[0],
            }
            for index, row in enumerate(rows, start=1)
        ],
    }
    _write_json(args.output / "merged_jobs.json", [job.model_dump(mode="json") for job in all_jobs])
    _write_json(args.output / "summary.json", summary)
    with (args.output / "review.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=list(review_rows[0]) if review_rows else ["case_id"]
        )
        writer.writeheader()
        writer.writerows(review_rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
