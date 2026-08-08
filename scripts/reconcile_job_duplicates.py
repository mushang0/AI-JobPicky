"""Report and explicitly reconcile duplicate job rows.

The default mode is read-only. ``--apply`` only merges groups whose canonical
identity and facts are safe, and refuses groups with saved/recommendation key
conflicts instead of deleting user-facing data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from jobpicky.config import Settings
from jobpicky.contracts import CollectedJob
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.job_catalog import (
    JOB_TABLE,
    _content_hash,
    _identity_key,
    _merge_metadata,
    _merge_unique_strings,
    _normalized_url,
)
from jobpicky.infrastructure.recommendation_store import RECOMMENDATION_TABLE
from jobpicky.infrastructure.saved_job_store import SAVED_JOB_TABLE


def _as_collected(row: Mapping[str, Any]) -> CollectedJob:
    return CollectedJob.model_construct(
        source_id=row["source_id"],
        source_job_id=row.get("source_job_id"),
        company_name=row["company_name"],
        company_nature=row.get("company_nature"),
        title=row["title"],
        locations=list(row.get("locations") or []),
        description=row.get("description"),
        detail_url=row.get("detail_url"),
        apply_url=row.get("apply_url"),
        recruitment_type=row.get("recruitment_type"),
        education_requirement=row.get("education_requirement"),
        salary_min=row.get("salary_min"),
        salary_max=row.get("salary_max"),
        salary_months=row.get("salary_months"),
        graduation_years=list(row.get("graduation_years") or []),
        published_at=row.get("published_at"),
        deadline_at=row.get("deadline_at"),
        metadata=dict(row.get("metadata") or {}),
    )


def _identity(row: Mapping[str, Any]) -> str:
    return _identity_key(_as_collected(row))


def _facts_match(rows: list[Mapping[str, Any]]) -> bool:
    return (
        len(
            {
                _content_hash(
                    _as_collected(row).model_copy(
                        update={
                            "detail_url": None,
                            "apply_url": None,
                            "graduation_years": [],
                            "metadata": {},
                        }
                    )
                )
                for row in rows
            }
        )
        == 1
    )


def _mergeable(rows: list[Mapping[str, Any]]) -> tuple[bool, str]:
    source_job_ids = {str(row["source_job_id"]) for row in rows if row.get("source_job_id")}
    detail_urls = {_normalized_url(str(row["detail_url"])) for row in rows if row.get("detail_url")}
    if source_job_ids and len(source_job_ids) == 1:
        if len(detail_urls) <= 1 or _facts_match(rows):
            return True, "same scoped source_job_id"
        return False, "same source_job_id has conflicting detail URL and facts"
    if len(detail_urls) == 1:
        return True, "same normalized detail URL"
    if _facts_match(rows):
        return True, "identical strong job facts"
    return False, "candidate identity has conflicting facts"


def _completeness(row: Mapping[str, Any]) -> int:
    fields = (
        "description",
        "detail_url",
        "apply_url",
        "company_nature",
        "recruitment_type",
        "education_requirement",
        "salary_min",
        "salary_max",
        "published_at",
        "deadline_at",
    )
    return sum(row.get(field) not in (None, "", []) for field in fields)


def _winner(rows: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    return max(
        rows,
        key=lambda row: (
            _completeness(row),
            row.get("last_confirmed_at") or datetime.min.replace(tzinfo=UTC),
            row.get("updated_at") or datetime.min.replace(tzinfo=UTC),
            str(row["id"]),
        ),
    )


def _group_report(
    rows: list[Mapping[str, Any]],
    saved_counts: Mapping[str, int],
    recommendation_counts: Mapping[str, int],
) -> dict[str, object]:
    mergeable, reason = _mergeable(rows)
    winner = _winner(rows)
    duplicate_ids = [str(row["id"]) for row in rows if row["id"] != winner["id"]]
    return {
        "identity_key": _identity(rows[0]),
        "job_ids": sorted(str(row["id"]) for row in rows),
        "winner_job_id": str(winner["id"]),
        "duplicate_job_ids": sorted(duplicate_ids),
        "source_ids": sorted({str(row["source_id"]) for row in rows}),
        "source_job_ids": sorted(
            {str(row["source_job_id"]) for row in rows if row.get("source_job_id")}
        ),
        "company_group_keys": sorted(
            {str(row["company_group_key"]) for row in rows if row.get("company_group_key")}
        ),
        "detail_urls": sorted({str(row["detail_url"]) for row in rows if row.get("detail_url")}),
        "safe_to_merge": mergeable,
        "reason": reason,
        "saved_references": sum(saved_counts.get(str(row["id"]), 0) for row in rows),
        "recommendation_references": sum(
            recommendation_counts.get(str(row["id"]), 0) for row in rows
        ),
    }


async def _load_rows(session: Any) -> list[Mapping[str, Any]]:
    result = await session.execute(sa.select(JOB_TABLE))
    return list(result.mappings())


async def _counts(session: Any, table: Any, job_ids: list[str]) -> dict[str, int]:
    if not job_ids:
        return {}
    result = await session.execute(
        sa.select(table.c.job_id, sa.func.count())
        .where(table.c.job_id.in_(job_ids))
        .group_by(table.c.job_id)
    )
    return {str(job_id): int(count) for job_id, count in result}


async def _reference_conflict(session: Any, winner_id: str, duplicate_ids: list[str]) -> bool:
    recommendation_rows = list(
        (
            await session.execute(
                sa.select(
                    RECOMMENDATION_TABLE.c.user_id,
                    RECOMMENDATION_TABLE.c.run_id,
                    RECOMMENDATION_TABLE.c.job_id,
                ).where(RECOMMENDATION_TABLE.c.job_id.in_([winner_id, *duplicate_ids]))
            )
        ).mappings()
    )
    winner_users = {row.user_id for row in recommendation_rows if row.job_id == winner_id}
    winner_runs = {row.run_id for row in recommendation_rows if row.job_id == winner_id}
    duplicate_rows = [row for row in recommendation_rows if row.job_id != winner_id]
    duplicate_users = [row.user_id for row in duplicate_rows]
    duplicate_runs = [row.run_id for row in duplicate_rows]
    return (
        any(
            row.job_id != winner_id and (row.user_id in winner_users or row.run_id in winner_runs)
            for row in recommendation_rows
        )
        or len(duplicate_users) != len(set(duplicate_users))
        or len(duplicate_runs) != len(set(duplicate_runs))
    )


async def _merge_group(session: Any, rows: list[Mapping[str, Any]]) -> None:
    winner = _winner(rows)
    winner_id = str(winner["id"])
    duplicate_ids = [str(row["id"]) for row in rows if row["id"] != winner_id]
    metadata: object = dict(winner.get("metadata") or {})
    for row in rows:
        if row["id"] == winner_id:
            continue
        metadata = _merge_metadata(
            metadata,
            row.get("metadata"),
            existing_source_id=winner.get("source_id"),
            incoming_source_id=row.get("source_id"),
        )
    all_batch_tokens = _merge_unique_strings(*(row.get("batch_tokens") for row in rows))
    first_seen = min(row["first_seen_at"] for row in rows)
    last_confirmed = max(row["last_confirmed_at"] for row in rows)
    latest = max(rows, key=lambda row: row["last_confirmed_at"])
    source_ids = sorted(str(row["source_id"]) for row in rows if row.get("source_id"))
    graduation_years = sorted(
        {
            year
            for row in rows
            for year in (row.get("graduation_years") or [])
            if isinstance(year, int)
        }
    )
    embedding = winner.get("embedding") or next(
        (row.get("embedding") for row in rows if row.get("embedding") is not None), None
    )
    await session.execute(
        sa.update(JOB_TABLE)
        .where(JOB_TABLE.c.id == winner_id)
        .values(
            source_id=source_ids[0] if source_ids else winner["source_id"],
            metadata=metadata,
            batch_tokens=all_batch_tokens,
            identity_key=_identity(rows[0]),
            first_seen_at=first_seen,
            last_confirmed_at=last_confirmed,
            updated_at=max(row["updated_at"] for row in rows),
            last_seen_run_id=latest.get("last_seen_run_id"),
            status="OPEN" if any(row.get("status") == "OPEN" for row in rows) else winner["status"],
            graduation_years=graduation_years,
            embedding=embedding,
        )
    )
    for duplicate_id in duplicate_ids:
        saved_rows = list(
            (
                await session.execute(
                    sa.select(SAVED_JOB_TABLE.c.user_id).where(
                        SAVED_JOB_TABLE.c.job_id == duplicate_id
                    )
                )
            ).scalars()
        )
        for user_id in saved_rows:
            exists = await session.scalar(
                sa.select(sa.literal(True)).where(
                    SAVED_JOB_TABLE.c.user_id == user_id,
                    SAVED_JOB_TABLE.c.job_id == winner_id,
                )
            )
            if exists:
                await session.execute(
                    sa.delete(SAVED_JOB_TABLE).where(
                        SAVED_JOB_TABLE.c.user_id == user_id,
                        SAVED_JOB_TABLE.c.job_id == duplicate_id,
                    )
                )
            else:
                await session.execute(
                    sa.update(SAVED_JOB_TABLE)
                    .where(
                        SAVED_JOB_TABLE.c.user_id == user_id,
                        SAVED_JOB_TABLE.c.job_id == duplicate_id,
                    )
                    .values(job_id=winner_id)
                )
        await session.execute(
            sa.update(RECOMMENDATION_TABLE)
            .where(RECOMMENDATION_TABLE.c.job_id == duplicate_id)
            .values(job_id=winner_id)
        )
    await session.execute(sa.delete(JOB_TABLE).where(JOB_TABLE.c.id.in_(duplicate_ids)))


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            rows = await _load_rows(session)
            grouped: dict[str, list[Mapping[str, Any]]] = {}
            for row in rows:
                grouped.setdefault(_identity(row), []).append(row)
            duplicate_groups = [group for group in grouped.values() if len(group) > 1]
            job_ids = [str(row["id"]) for group in duplicate_groups for row in group]
            saved_counts = await _counts(session, SAVED_JOB_TABLE, job_ids)
            recommendation_counts = await _counts(session, RECOMMENDATION_TABLE, job_ids)
            reports = [
                _group_report(group, saved_counts, recommendation_counts)
                for group in duplicate_groups
            ]

        for report in reports:
            if report["safe_to_merge"] and report["recommendation_references"]:
                async with factory() as session:
                    if await _reference_conflict(
                        session,
                        str(report["winner_job_id"]),
                        [str(job_id) for job_id in report["duplicate_job_ids"]],
                    ):
                        report["safe_to_merge"] = False
                        report["reason"] = "recommendation unique-key conflict"

        report_document = {
            "generated_at": datetime.now(UTC).isoformat(),
            "job_count": len(rows),
            "duplicate_group_count": len(reports),
            "duplicate_row_count": sum(len(report["duplicate_job_ids"]) for report in reports),
            "safe_group_count": sum(bool(report["safe_to_merge"]) for report in reports),
            "groups": reports,
        }
        if args.output:
            args.output.write_text(
                json.dumps(report_document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(
            "duplicate report: "
            f"{report_document['duplicate_group_count']} groups, "
            f"{report_document['duplicate_row_count']} extra rows, "
            f"{report_document['safe_group_count']} safe groups"
        )
        if reports:
            largest = max(reports, key=lambda report: len(report["duplicate_job_ids"]))
            print(
                "largest group: "
                f"winner={largest['winner_job_id']} "
                f"duplicates={len(largest['duplicate_job_ids'])} "
                f"source_job_ids={largest['source_job_ids'][:3]}"
            )
        if not args.apply and not args.rekey:
            return 0

        if args.apply:
            async with factory() as session, session.begin():
                for group in duplicate_groups:
                    report = next(
                        item for item in reports if item["identity_key"] == _identity(group[0])
                    )
                    if not report["safe_to_merge"]:
                        continue
                    if await _reference_conflict(
                        session,
                        str(report["winner_job_id"]),
                        [str(job_id) for job_id in report["duplicate_job_ids"]],
                    ):
                        continue
                    await _merge_group(session, group)
            print("duplicate reconciliation applied")

        if args.rekey:
            async with factory() as session, session.begin():
                for identity_key, group in grouped.items():
                    if len(group) != 1:
                        continue
                    await session.execute(
                        sa.update(JOB_TABLE)
                        .where(JOB_TABLE.c.id == group[0]["id"])
                        .values(identity_key=identity_key)
                    )
            print("singleton job identities rekeyed")
        return 0
    except Exception as exc:
        print(f"duplicate reconciliation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await engine.dispose()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write the read-only JSON report to this path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="merge only safe groups; omit this flag for a read-only report",
    )
    parser.add_argument(
        "--rekey",
        action="store_true",
        help="rewrite identity_key for rows with one unambiguous canonical identity",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parse_args())))
