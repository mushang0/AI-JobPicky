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
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="最多写入岗位数；不指定则全部写入",
    )
    parser.add_argument(
        "--row-limit",
        type=int,
        default=None,
        help="最多读取表格记录数；在解析前截断输入",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="清空开发岗位数据后重新灌入；仅 development/test 环境可用",
    )
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.reset and settings.environment not in {"development", "dev", "test"}:
        parser.error("--reset 仅允许在 development、dev 或 test 环境使用")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit 不能小于 0")
    if args.reset and args.limit == 0:
        parser.error("--reset 需要 --limit 至少为 1")
    if args.row_limit is not None and args.row_limit < 0:
        parser.error("--row-limit 不能小于 0")

    rows = read_rows(args.csv, args.sheet)
    if args.row_limit is not None:
        rows = rows[: args.row_limit]
    for row in rows:
        if not row.apply_links:
            print(f"[warning] row={row.row_number} reason=no supported application link")
    pipeline_results = run_pipeline_by_source(rows)

    total_jobs = sum(len(pipeline_result.batch.items) for pipeline_result in pipeline_results)
    parsed_jobs = sum(
        item.metadata.get("collection_mode") == "PARSED"
        for pipeline_result in pipeline_results
        for item in pipeline_result.batch.items
    )
    fallback_jobs = total_jobs - parsed_jobs
    if args.reset and total_jobs == 0:
        raise RuntimeError("解析没有得到任何岗位，已中止重置以保护现有开发数据")

    engine = create_engine(settings.database_url)
    catalog = PostgresJobCatalog(create_session_factory(engine))
    run_id = f"campus-csv-{uuid4()}"
    remaining = args.limit
    created = updated = unchanged = 0
    unsupported = 0
    try:
        if args.reset:
            await catalog.reset_development_data()
            print("reset=development-job-data")
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
            if remaining is not None and len(batch.items) > remaining:
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
            if remaining is not None:
                remaining -= len(batch.items)
    finally:
        await engine.dispose()

    print(
        f"created={created} updated={updated} unchanged={unchanged} "
        f"collected_jobs={total_jobs} parsed_jobs={parsed_jobs} "
        f"fallback_jobs={fallback_jobs} rows={len(rows)} "
        f"sources={len(pipeline_results)} unsupported={unsupported}"
    )


if __name__ == "__main__":
    asyncio.run(main())
