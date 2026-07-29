"""Run the fixed recruitment-sheet collection pipeline and write collected jobs."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from jobpicky.collection.pipeline import run_pipeline
from jobpicky.collection.spreadsheet import read_rows
from jobpicky.config import Settings
from jobpicky.contracts import CollectedJob, JobFact, JobStatus
from jobpicky.infrastructure.database import create_engine

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "campus_jobs_sample.csv"
SOURCE_ID = "wanqing-campus-sheet"


def collected_to_fact(collected: CollectedJob, now: datetime) -> JobFact:
    identity = (
        collected.source_job_id
        or collected.detail_url
        or (f"{collected.company_name}|{collected.title}")
    )
    job_id = "wq-" + hashlib.sha1(identity.encode()).hexdigest()[:12]
    fact_version = hashlib.sha1(
        f"{collected.company_name}|{collected.title}|{collected.description}".encode()
    ).hexdigest()[:8]
    return JobFact(
        id=job_id,
        source_id=collected.source_id,
        company_name=collected.company_name,
        company_nature=collected.company_nature,
        title=collected.title,
        locations=collected.locations,
        description=collected.description,
        detail_url=collected.detail_url,
        apply_url=collected.apply_url,
        recruitment_type=collected.recruitment_type,
        education_requirement=collected.education_requirement,
        salary_min=collected.salary_min,
        salary_max=collected.salary_max,
        salary_months=collected.salary_months,
        graduation_years=collected.graduation_years,
        status=JobStatus.OPEN,
        fact_version=fact_version,
        published_at=collected.published_at,
        deadline_at=collected.deadline_at,
        first_seen_at=now,
        last_confirmed_at=now,
        updated_at=now,
    )


INSERT_SQL = text("""
    INSERT INTO job (id, source_id, company_name, company_nature, title, locations,
                     description, detail_url, apply_url, recruitment_type,
                     education_requirement, salary_min, salary_max, salary_months,
                     graduation_years, status, fact_version, published_at,
                     deadline_at, first_seen_at, last_confirmed_at, updated_at)
    VALUES (:id, :source_id, :company_name, :company_nature, :title, :locations,
            :description, :detail_url, :apply_url, :recruitment_type,
            :education_requirement, :salary_min, :salary_max, :salary_months,
            :graduation_years, :status, :fact_version, :published_at,
            :deadline_at, :first_seen_at, :last_confirmed_at, :updated_at)
    ON CONFLICT (id) DO NOTHING
""")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV/XLSX 文件路径")
    parser.add_argument("--sheet", default=None, help="XLSX 工作表名称")
    parser.add_argument("--limit", type=int, default=1000, help="最多写入条数")
    args = parser.parse_args()

    rows = read_rows(args.csv, args.sheet)
    result = run_pipeline(SOURCE_ID, rows)
    now = datetime.now(UTC)
    facts = [collected_to_fact(item, now) for item in result.batch.items[: args.limit]]

    engine = create_engine(Settings.from_env().database_url)
    async with engine.begin() as conn:
        for fact in facts:
            await conn.execute(
                INSERT_SQL,
                {
                    "id": fact.id,
                    "source_id": fact.source_id,
                    "company_name": fact.company_name,
                    "company_nature": fact.company_nature,
                    "title": fact.title,
                    "locations": fact.locations,
                    "description": fact.description,
                    "detail_url": fact.detail_url,
                    "apply_url": fact.apply_url,
                    "recruitment_type": fact.recruitment_type,
                    "education_requirement": fact.education_requirement,
                    "salary_min": fact.salary_min,
                    "salary_max": fact.salary_max,
                    "salary_months": fact.salary_months,
                    "graduation_years": fact.graduation_years,
                    "status": fact.status.value,
                    "fact_version": fact.fact_version,
                    "published_at": fact.published_at,
                    "deadline_at": fact.deadline_at,
                    "first_seen_at": fact.first_seen_at,
                    "last_confirmed_at": fact.last_confirmed_at,
                    "updated_at": fact.updated_at,
                },
            )
    await engine.dispose()
    for failure in result.unsupported:
        print(
            f"[unsupported] row={failure.row_number} type={failure.link_type} "
            f"url={failure.url} reason={failure.reason}"
        )
    print(
        f"inserted={len(facts)} rows={len(rows)} "
        f"unsupported={len(result.unsupported)} complete={result.batch.complete}"
    )


if __name__ == "__main__":
    asyncio.run(main())
