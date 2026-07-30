"""Run the fixed recruitment-sheet collection pipeline and write collected jobs."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from jobpicky.collection.pipeline import run_pipeline_by_source
from jobpicky.collection.spreadsheet import read_rows
from jobpicky.config import Settings
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.job_catalog import PostgresJobCatalog

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "campus_jobs_sample.csv"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV/XLSX 文件路径")
    parser.add_argument("--sheet", default=None, help="XLSX 工作表名称")
    parser.add_argument("--limit", type=int, default=1000, help="最多写入条数")
    args = parser.parse_args()

    rows = read_rows(args.csv, args.sheet)
    for row in rows:
        if not row.apply_links:
            print(f"[warning] row={row.row_number} reason=no supported application link")
    pipeline_results = run_pipeline_by_source(rows)

    engine = create_engine(Settings.from_env().database_url)
    catalog = PostgresJobCatalog(create_session_factory(engine))
    run_id = f"campus-csv-{uuid4()}"
    remaining = max(args.limit, 0)
    created = updated = unchanged = 0
    unsupported = 0
    try:
        for pipeline_result in pipeline_results:
            for failure in pipeline_result.unsupported:
                print(
                    f"[unsupported] row={failure.row_number} type={failure.link_type} "
                    f"url={failure.url} reason={failure.reason}"
                )
            unsupported += len(pipeline_result.unsupported)
            if remaining == 0:
                continue
            batch = pipeline_result.batch
            if len(batch.items) > remaining:
                batch = batch.model_copy(
                    update={
                        "items": batch.items[:remaining],
                        "complete": False,
                        "warnings": [*batch.warnings, f"limited to {args.limit} jobs"],
                    }
                )
            ingestion = await catalog.ingest(run_id, batch)
            created += ingestion.created_count
            updated += ingestion.updated_count
            unchanged += ingestion.unchanged_count
            remaining -= len(batch.items)
    finally:
        await engine.dispose()

    print(
        f"created={created} updated={updated} unchanged={unchanged} "
        f"rows={len(rows)} sources={len(pipeline_results)} unsupported={unsupported}"
    )


if __name__ == "__main__":
    asyncio.run(main())
