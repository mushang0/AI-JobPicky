"""校招汇总表 CSV → job 表的一次性灌库脚本（开发用样本数据）。

用法：
    docker compose up -d db
    uv run alembic upgrade head
    uv run python scripts/ingest_campus_csv.py                 # 默认样本 + 前 1000 条
    uv run python scripts/ingest_campus_csv.py --limit 500    # 调整条数
    uv run python scripts/ingest_campus_csv.py --csv 路径      # 换数据源

说明：
- 解析 → CollectedJob 契约校验 → JobFact 契约校验 → 写入 job 表；
- 岗位身份用公告链接哈希（来源无稳定岗位 ID，架构 §5.2 第二优先级）；
- 幂等：同一链接重复执行不新增（ON CONFLICT DO NOTHING）；
- "尽快投递" 等非日期截止时间、缺失薪资 → NULL，未知不伪造；
- 行业分类 / 是否笔试 / 公告来源 / 批次原文 → metadata，不进核心字段。

正式的 SourceCollectorPort 采集器切片落地后，本脚本可由其实现替代。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from jobpicky.config import Settings
from jobpicky.contracts import CollectedJob, JobFact, JobStatus
from jobpicky.infrastructure.database import create_engine

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "raw" / "campus_jobs_sample.csv"
SOURCE_ID = "wanqing-campus-sheet"
NOW = datetime.now(UTC)

GRAD_YEAR_RE = re.compile(r"(\d{4})\s*届")
# 汇总表的表头/说明行，不是岗位数据
JUNK_COMPANIES = {"公司名称"}
JUNK_TITLES = {"招聘岗位", "（必看）表格使用说明"}


def clean(value: str) -> str:
    return value.strip().strip("﻿")


def valid_text(value: str) -> str | None:
    text_value = clean(value)
    return text_value if text_value and text_value != "/" else None


def valid_url(value: str) -> str | None:
    text_value = clean(value)
    return text_value if text_value.startswith("http") else None


def parse_locations(value: str) -> list[str]:
    parts = re.split(r"[,，、]", value)
    return [p.strip() for p in parts if p.strip()]


def parse_graduation_years(value: str) -> list[int]:
    return [int(y) for y in GRAD_YEAR_RE.findall(value)]


def parse_date(value: str) -> datetime | None:
    text_value = clean(value)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text_value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_recruitment_type(batch: str) -> str | None:
    if "实习" in batch:
        return "实习"
    if "秋招" in batch or "春招" in batch or "校园招聘" in batch:
        return "校招"
    return valid_text(batch)


def parse_row(row: list[str]) -> JobFact | None:
    company = clean(row[1])
    title = clean(row[4])
    if not company or not title or company in JUNK_COMPANIES or title in JUNK_TITLES:
        return None

    detail_url = valid_url(row[11]) if len(row) > 11 else None
    apply_url = valid_url(row[12]) if len(row) > 12 else None
    identity = detail_url or f"{company}|{title}"
    job_id = "wq-" + hashlib.sha1(identity.encode()).hexdigest()[:12]

    collected = CollectedJob(
        source_id=SOURCE_ID,
        source_job_id=None,
        company_name=company,
        company_nature=valid_text(row[2]),
        title=title,
        locations=parse_locations(row[5]),
        description=valid_text(row[13]) if len(row) > 13 else None,
        detail_url=detail_url,
        apply_url=apply_url,
        recruitment_type=parse_recruitment_type(clean(row[9])),
        education_requirement=valid_text(row[8]),
        graduation_years=parse_graduation_years(row[7]),
        published_at=parse_date(row[0]),
        deadline_at=parse_date(row[6]),
        metadata={
            k: v
            for k, v in {
                "industry": valid_text(row[3]),
                "has_written_test": valid_text(row[14]) if len(row) > 14 else None,
                "announcement_source": valid_text(row[10]),
                "batch": valid_text(row[9]),
            }.items()
            if v is not None
        },
    )

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
        graduation_years=collected.graduation_years,
        status=JobStatus.OPEN,
        fact_version=fact_version,
        published_at=collected.published_at,
        deadline_at=collected.deadline_at,
        first_seen_at=NOW,
        last_confirmed_at=NOW,
        updated_at=NOW,
    )


INSERT_SQL = text("""
    INSERT INTO job (id, source_id, company_name, company_nature, title, locations,
                     description, detail_url, apply_url, recruitment_type,
                     education_requirement, salary_min, salary_max, salary_months,
                     graduation_years, status, fact_version, published_at,
                     deadline_at, first_seen_at, last_confirmed_at, updated_at)
    VALUES (:id, :source_id, :company_name, :company_nature, :title, :locations,
            :description, :detail_url, :apply_url, :recruitment_type,
            :education_requirement, NULL, NULL, NULL,
            :graduation_years, :status, :fact_version, :published_at,
            :deadline_at, :first_seen_at, :last_confirmed_at, :updated_at)
    ON CONFLICT (id) DO NOTHING
""")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="CSV 文件路径")
    parser.add_argument("--limit", type=int, default=1000, help="最多入库条数")
    args = parser.parse_args()

    facts: list[JobFact] = []
    seen: set[str] = set()
    skipped = 0
    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(facts) >= args.limit:
                break
            if len(row) < 10:
                skipped += 1
                continue
            try:
                fact = parse_row(row)
            except Exception as exc:  # noqa: BLE001 - 单行坏数据不阻断整批
                skipped += 1
                print(f"[skip] {row[1][:20] if len(row) > 1 else '?'}: {exc}")
                continue
            if fact is None or fact.id in seen:
                skipped += 1
                continue
            seen.add(fact.id)
            facts.append(fact)

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
    print(f"inserted={len(facts)} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
