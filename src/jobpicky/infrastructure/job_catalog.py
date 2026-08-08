from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

try:
    from pgvector.sqlalchemy import Vector
except ModuleNotFoundError:  # pragma: no cover - only used by dependency-light offline tests

    class Vector(sa.types.UserDefinedType[object]):  # type: ignore[no-redef]
        cache_ok = True

        def __init__(self, dimension: int) -> None:
            self.dimension = dimension

        def get_col_spec(self, **_: object) -> str:
            return f"vector({self.dimension})"


from ..catalog import apply_filter, extract_terms, term_hit_score
from ..contracts import (
    CollectedJob,
    CollectionBatch,
    ErrorCode,
    FilterResult,
    HardFilterSpec,
    IngestionResult,
    JobFact,
    RetrievalChannel,
    SearchHit,
)
from ..contracts.normalization import (
    normalize_company_group_key,
    normalize_company_nature,
    normalize_education,
    normalize_locations,
    normalize_recruitment_type,
    split_batch_values,
)
from ..errors import ApplicationError
from ..ports import EmbeddingPort
from .source_store import JOB_SOURCE_TABLE

# Lightweight Core mapping of the job table for read queries. The Alembic
# migrations remain the single source of truth for the schema (plan 003).
JOB_TABLE = sa.table(
    "job",
    sa.column("id", sa.String),
    sa.column("source_id", sa.String),
    sa.column("company_name", sa.String),
    sa.column("company_nature", sa.String),
    sa.column("title", sa.String),
    sa.column("locations", postgresql.ARRAY(sa.String)),
    sa.column("description", sa.Text),
    sa.column("metadata", postgresql.JSONB),
    sa.column("batch_tokens", postgresql.ARRAY(sa.String)),
    sa.column("company_group_key", sa.String),
    sa.column("detail_url", sa.String),
    sa.column("apply_url", sa.String),
    sa.column("recruitment_type", sa.String),
    sa.column("education_requirement", sa.String),
    sa.column("salary_min", sa.Integer),
    sa.column("salary_max", sa.Integer),
    sa.column("salary_months", sa.Integer),
    sa.column("graduation_years", postgresql.ARRAY(sa.Integer)),
    sa.column("status", sa.String),
    sa.column("fact_version", sa.String),
    sa.column("published_at", sa.DateTime(timezone=True)),
    sa.column("deadline_at", sa.DateTime(timezone=True)),
    sa.column("first_seen_at", sa.DateTime(timezone=True)),
    sa.column("last_confirmed_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("embedding", Vector(512)),
    sa.column("identity_key", sa.String),
    sa.column("source_job_id", sa.String),
    sa.column("content_hash", sa.String),
    sa.column("last_seen_run_id", sa.String),
)

_CLOSE_WARNING = (
    "historical jobs were not closed: pagination completeness and source scope "
    "are not yet sufficient for safe closing"
)
_SPACE_RE = re.compile(r"\s+")
_SOURCE_DISPLAY_NAMES = {
    "MOKA": "Moka",
    "FEISHU": "飞书招聘",
    "FEISHU_RECRUITMENT": "飞书招聘",
    "BEISEN": "北森",
    "JOB_51": "前程无忧",
    "ZHAOPIN": "智联招聘",
    "GUOPIN": "国聘",
    "WECHAT": "微信公众号",
    "HOTJOB": "HotJob",
    "OFFICIAL_WEBSITE": "企业官网",
    "OFFICIAL_WEB": "企业官网",
    "PUBLIC_WEB": "公开招聘公告",
    "PUBLIC_RECRUITMENT": "公开招聘公告",
    "PUBLIC_ANNOUNCEMENT": "公开招聘公告",
}

_PROVENANCE_METADATA_KEYS = frozenset(
    {
        "feishu_record_id",
        "feishu_record_ids",
        "feishu_last_modified_at",
        "sheet_updated_at",
        "table_row_number",
        "source_id",
        "source_ids",
        "source_url",
        "fallback_source_url",
        "batch",
    }
)
_IDENTITY_HOST_SUFFIXES = (
    "jobs.feishu.cn",
    "mokahr.com",
    "zhiye.com",
    "beisen.com",
    "zhaopin.com",
    "51job.com",
    "iguopin.com",
    "hotjob.cn",
)


def _normalized_text(value: str) -> str:
    return _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _identity_scope(job: CollectedJob) -> str:
    metadata = job.metadata
    platform = metadata.get("platform_family") or metadata.get("parser") or metadata.get("platform")
    if not isinstance(platform, str) or not platform.strip():
        for url in (job.detail_url, job.apply_url):
            if not url:
                continue
            hostname = urlsplit(url).hostname
            if hostname:
                hostname = hostname.casefold().rstrip(".")
                if any(
                    hostname == suffix or hostname.endswith(f".{suffix}")
                    for suffix in _IDENTITY_HOST_SUFFIXES
                ):
                    platform = f"host:{hostname}"
                    break
    if not isinstance(platform, str) or not platform.strip():
        platform = job.source_id
    return f"{_normalized_text(platform)}:{normalize_company_group_key(job.company_name, metadata)}"


def _fact_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in metadata.items() if key not in _PROVENANCE_METADATA_KEYS}


def _normalized_identifier(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _normalized_url(value: str) -> str:
    parts = urlsplit(value.strip())
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{hostname}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: (
            item.astimezone(UTC).isoformat() if isinstance(item, datetime) else str(item)
        ),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identity_key(job: CollectedJob) -> str:
    scope = _identity_scope(job)
    if job.source_job_id:
        evidence: object = ["source_job_id", scope, _normalized_identifier(job.source_job_id)]
    elif job.detail_url:
        evidence = ["detail_url", scope, _normalized_url(job.detail_url)]
    else:
        values = _normalized_filter_values(job)
        evidence = [
            "facts",
            scope,
            _normalized_text(job.company_name),
            _normalized_text(job.title),
            sorted(_normalized_text(location) for location in normalize_locations(job.locations)),
            values["recruitment_type"],
            values["education_requirement"],
            job.salary_min,
            job.salary_max,
            job.salary_months,
            sorted(job.graduation_years),
            job.description,
        ]
    return _digest(evidence)


def _content_hash(job: CollectedJob) -> str:
    values = _normalized_filter_values(job)
    return _digest(
        {
            "company_name": job.company_name,
            "company_nature": values["company_nature"],
            "title": job.title,
            "locations": values["locations"],
            "description": job.description,
            "metadata": _fact_metadata(job.metadata),
            "detail_url": job.detail_url,
            "apply_url": job.apply_url,
            "recruitment_type": values["recruitment_type"],
            "education_requirement": values["education_requirement"],
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_months": job.salary_months,
            "graduation_years": job.graduation_years,
            "published_at": job.published_at,
            "deadline_at": job.deadline_at,
        }
    )


def _source_display_name(source_id: str, items: Sequence[CollectedJob]) -> str:
    platforms = {
        str(item.metadata.get("platform", "")).strip().upper()
        for item in items
        if item.metadata.get("platform")
    }
    known = {
        _SOURCE_DISPLAY_NAMES[platform]
        for platform in platforms
        if platform in _SOURCE_DISPLAY_NAMES
    }
    if len(known) == 1:
        return next(iter(known))
    source_key = source_id.strip().upper()
    for platform, display_name in _SOURCE_DISPLAY_NAMES.items():
        if platform in source_key:
            return display_name
    return "公开招聘公告"


def _job_values(
    job: CollectedJob,
    *,
    identity_key: str,
    content_hash: str,
    run_id: str,
) -> dict[str, object]:
    normalized = _normalized_filter_values(job)
    metadata = normalized["metadata"]
    assert isinstance(metadata, dict)
    return {
        "source_id": job.source_id,
        "company_name": job.company_name,
        "company_nature": normalized["company_nature"],
        "title": job.title,
        "locations": normalized["locations"],
        "description": job.description,
        "metadata": metadata,
        "batch_tokens": split_batch_values(
            metadata.get("batch") if isinstance(metadata.get("batch"), str) else None
        ),
        "company_group_key": normalize_company_group_key(job.company_name, metadata),
        "detail_url": job.detail_url,
        "apply_url": job.apply_url,
        "recruitment_type": normalized["recruitment_type"],
        "education_requirement": normalized["education_requirement"],
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_months": job.salary_months,
        "graduation_years": job.graduation_years,
        "published_at": job.published_at,
        "deadline_at": job.deadline_at,
        "identity_key": identity_key,
        "source_job_id": job.source_job_id,
        "content_hash": content_hash,
        "last_seen_run_id": run_id,
    }


def _normalized_filter_values(job: CollectedJob) -> dict[str, object]:
    locations = normalize_locations(job.locations)
    company_nature = normalize_company_nature(job.company_nature)
    recruitment_type = normalize_recruitment_type(job.recruitment_type)
    education = normalize_education(job.education_requirement)
    metadata = dict(job.metadata)
    original: dict[str, JsonValue] = {}
    for field, raw, normalized in (
        ("company_nature", job.company_nature, company_nature),
        ("recruitment_type", job.recruitment_type, recruitment_type),
        ("education_requirement", job.education_requirement, education),
        ("locations", job.locations, locations),
    ):
        if raw != normalized and raw is not None:
            original[field] = cast(JsonValue, raw)
    if original:
        existing = metadata.get("_normalization_v1_original")
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(original)
        metadata["_normalization_v1_original"] = merged
    return {
        "company_nature": company_nature,
        "recruitment_type": recruitment_type,
        "education_requirement": education,
        "locations": locations,
        "metadata": metadata,
    }


def _string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _merge_unique_strings(*values: object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in _string_values(value):
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                result.append(item)
    return result


def _merge_metadata(
    existing: object,
    incoming: object,
    *,
    existing_source_id: object,
    incoming_source_id: object,
) -> dict[str, object]:
    old = dict(existing) if isinstance(existing, Mapping) else {}
    new = dict(incoming) if isinstance(incoming, Mapping) else {}
    merged = {**old, **new}

    old_original = old.get("_normalization_v1_original")
    new_original = new.get("_normalization_v1_original")
    if isinstance(old_original, Mapping) or isinstance(new_original, Mapping):
        merged["_normalization_v1_original"] = {
            **(dict(old_original) if isinstance(old_original, Mapping) else {}),
            **(dict(new_original) if isinstance(new_original, Mapping) else {}),
        }

    old_record_ids = _merge_unique_strings(
        old.get("feishu_record_ids"),
        old.get("feishu_record_id"),
    )
    new_record_ids = _merge_unique_strings(
        new.get("feishu_record_ids"),
        new.get("feishu_record_id"),
    )
    record_ids = _merge_unique_strings(old_record_ids, new_record_ids)
    if record_ids and (
        len({item.casefold() for item in (*old_record_ids, *new_record_ids)}) > 1
        or "feishu_record_ids" in old
        or "feishu_record_ids" in new
    ):
        merged["feishu_record_ids"] = record_ids

    old_source_ids = _merge_unique_strings(old.get("source_ids"), existing_source_id)
    new_source_ids = _merge_unique_strings(new.get("source_ids"), incoming_source_id)
    source_ids = _merge_unique_strings(
        old_source_ids,
        new_source_ids,
    )
    if source_ids and (
        len({item.casefold() for item in (*old_source_ids, *new_source_ids)}) > 1
        or "source_ids" in old
        or "source_ids" in new
    ):
        merged["source_ids"] = source_ids
    return merged


def _merge_existing_values(
    existing: Mapping[str, object], incoming: dict[str, object]
) -> dict[str, object]:
    values = dict(incoming)
    values["metadata"] = _merge_metadata(
        existing.get("metadata"),
        incoming.get("metadata"),
        existing_source_id=existing.get("source_id"),
        incoming_source_id=incoming.get("source_id"),
    )
    values["batch_tokens"] = _merge_unique_strings(
        existing.get("batch_tokens"), incoming.get("batch_tokens")
    )
    if values.get("company_nature") is None and existing.get("company_nature") is not None:
        values["company_nature"] = existing["company_nature"]
    if values.get("recruitment_type") is None and existing.get("recruitment_type") is not None:
        values["recruitment_type"] = existing["recruitment_type"]
    old_source_id = str(existing.get("source_id") or "")
    new_source_id = str(incoming.get("source_id") or "")
    values["source_id"] = min(filter(None, (old_source_id, new_source_id)), default=new_source_id)
    return values


def row_to_job_fact(row: sa.RowMapping) -> JobFact:
    return JobFact(
        id=row.id,
        source_id=row.source_id,
        company_name=row.company_name,
        company_nature=row.company_nature,
        title=row.title,
        locations=list(row.locations),
        description=row.description,
        detail_url=row.detail_url,
        apply_url=row.apply_url,
        recruitment_type=row.recruitment_type,
        education_requirement=row.education_requirement,
        salary_min=row.salary_min,
        salary_max=row.salary_max,
        salary_months=row.salary_months,
        graduation_years=list(row.graduation_years or []),
        status=row.status,
        fact_version=row.fact_version,
        published_at=row.published_at,
        deadline_at=row.deadline_at,
        first_seen_at=row.first_seen_at,
        last_confirmed_at=row.last_confirmed_at,
        updated_at=row.updated_at,
        metadata=dict(row.metadata or {}),
    )


class PostgresJobCatalog:
    """PostgreSQL implementation of JobCatalogPort.

    Rows are read into JobFact contracts and all judgement happens in the
    pure catalog functions: the data volume is campus-sample scale, so a
    single source of deterministic, offline-testable logic beats SQL pushdown
    (plan 003, decision 2).

    Ingestion owns stable job identity and fact lifecycle. Semantic search is
    backed by the injected embedding port and pgvector.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding: EmbeddingPort | None = None,
        *,
        semantic_limit: int = 50,
    ) -> None:
        self._session_factory = session_factory
        self._embedding = embedding
        if semantic_limit < 1:
            raise ValueError("semantic_limit must be at least 1")
        self._semantic_limit = semantic_limit

    async def ingest(self, run_id: str, batch: CollectionBatch) -> IngestionResult:
        unique: dict[str, tuple[CollectedJob, str]] = {}
        for job in batch.items:
            identity_key = _identity_key(job)
            content_hash = _content_hash(job)
            previous = unique.get(identity_key)
            if previous and previous[1] != content_hash:
                raise ApplicationError(
                    ErrorCode.CONFLICT,
                    "one collection batch contains conflicting facts for the same job identity",
                    details={"source_id": batch.source_id},
                    run_id=run_id,
                )
            unique.setdefault(identity_key, (job, content_hash))

        created_count = 0
        updated_count = 0
        unchanged_count = 0
        job_ids: list[str] = []

        async with self._session_factory() as session, session.begin():
            display_name = _source_display_name(
                batch.source_id, list(unique_job[0] for unique_job in unique.values())
            )
            source_insert = postgresql.insert(JOB_SOURCE_TABLE).values(
                id=batch.source_id,
                display_name=display_name,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            await session.execute(
                source_insert.on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "display_name": source_insert.excluded.display_name,
                        "updated_at": source_insert.excluded.updated_at,
                    },
                    where=JOB_SOURCE_TABLE.c.display_name == JOB_SOURCE_TABLE.c.id,
                )
            )
            for identity_key, (job, content_hash) in sorted(unique.items()):
                await session.execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": identity_key},
                )
                result = await session.execute(
                    sa.select(JOB_TABLE)
                    .where(JOB_TABLE.c.identity_key == identity_key)
                    .with_for_update()
                )
                existing = result.mappings().one_or_none()
                now = datetime.now(UTC)
                values = _job_values(
                    job,
                    identity_key=identity_key,
                    content_hash=content_hash,
                    run_id=run_id,
                )
                if existing is None:
                    job_id = f"job-{identity_key[:24]}"
                    await session.execute(
                        sa.insert(JOB_TABLE).values(
                            id=job_id,
                            **values,
                            status="OPEN",
                            fact_version=content_hash,
                            first_seen_at=now,
                            last_confirmed_at=now,
                            updated_at=now,
                        )
                    )
                    created_count += 1
                else:
                    job_id = existing.id
                    values = _merge_existing_values(cast(Mapping[str, object], existing), values)
                    facts_changed = existing.content_hash != content_hash
                    provenance_changed = any(
                        existing.get(field) != values.get(field)
                        for field in ("source_id", "metadata", "batch_tokens", "company_group_key")
                    )
                    changed = facts_changed or provenance_changed or existing.status != "OPEN"
                    if changed:
                        update_values: dict[str, object] = {
                            **values,
                            "status": "OPEN",
                            "fact_version": content_hash,
                            "last_confirmed_at": now,
                            "updated_at": now,
                        }
                        if facts_changed:
                            update_values["embedding"] = None
                        await session.execute(
                            sa.update(JOB_TABLE)
                            .where(JOB_TABLE.c.id == job_id)
                            .values(**update_values)
                        )
                        updated_count += 1
                    else:
                        await session.execute(
                            sa.update(JOB_TABLE)
                            .where(JOB_TABLE.c.id == job_id)
                            .values(last_confirmed_at=now, last_seen_run_id=run_id)
                        )
                        unchanged_count += 1
                job_ids.append(job_id)

        return IngestionResult(
            job_ids=job_ids,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            closed_count=0,
            close_skipped=True,
            complete_accepted=False,
            warnings=[*batch.warnings, _CLOSE_WARNING],
        )

    async def reset_development_data(self) -> None:
        """Clear the job catalog and rows that reference its jobs.

        This is intentionally a separate, explicit operation for rebuilding a
        development database from the latest collection code.  It preserves
        the schema and user/account data; PostgreSQL cascades only through
        tables that reference ``job`` or ``job_source``.
        """
        async with self._session_factory() as session, session.begin():
            await session.execute(
                sa.text("TRUNCATE TABLE job, job_source RESTART IDENTITY CASCADE")
            )

    async def get_jobs(self, job_ids: Sequence[str]) -> list[JobFact]:
        if not job_ids:
            return []
        async with self._session_factory() as session:
            result = await session.execute(sa.select(JOB_TABLE).where(JOB_TABLE.c.id.in_(job_ids)))
            by_id = {row.id: row_to_job_fact(row) for row in result.mappings()}
        return [by_id[job_id] for job_id in job_ids if job_id in by_id]

    async def hard_filter(self, spec: HardFilterSpec) -> FilterResult:
        async with self._session_factory() as session:
            result = await session.execute(sa.select(JOB_TABLE))
            jobs = [row_to_job_fact(row) for row in result.mappings()]
        return apply_filter(spec, jobs)

    async def keyword_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        terms = extract_terms(query_text)
        if not terms or not eligible_job_ids:
            return []
        jobs = await self.get_jobs(eligible_job_ids)
        hits = [
            SearchHit(
                job_id=job.id,
                score=term_hit_score(terms, job),
                channel=RetrievalChannel.KEYWORD,
            )
            for job in jobs
        ]
        positive = [hit for hit in hits if hit.score > 0]
        return sorted(positive, key=lambda hit: (-hit.score, hit.job_id))

    async def semantic_search(
        self,
        query_text: str,
        eligible_job_ids: Sequence[str],
    ) -> list[SearchHit]:
        if not eligible_job_ids or not query_text.strip():
            return []
        if self._embedding is None:
            raise ApplicationError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "semantic search requires a configured embedding dependency",
                status_code=503,
                details={"dependency": "embedding", "stage": "RETRIEVE"},
            )

        query_vector = await self._embedding.embed_query(query_text)
        if len(query_vector) != 512:
            raise ApplicationError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "embedding query vector has an invalid dimension",
                status_code=503,
                details={"dependency": "embedding", "expected_dimension": 512},
            )

        # Use the pgvector cosine-distance operator directly so the query is
        # identical with or without the optional Python comparator helper.
        distance = JOB_TABLE.c.embedding.op("<=>", return_type=sa.Float())(query_vector).label(
            "distance"
        )
        async with self._session_factory() as session:
            result = await session.execute(
                sa.select(JOB_TABLE.c.id, distance)
                .where(
                    JOB_TABLE.c.id.in_(eligible_job_ids),
                    JOB_TABLE.c.embedding.is_not(None),
                )
                .order_by(distance.asc(), JOB_TABLE.c.id.asc())
                .limit(self._semantic_limit)
            )
            rows = result.mappings().all()

        return [
            SearchHit(
                job_id=row.id,
                score=max(0.0, min(1.0, 1.0 - float(row.distance))),
                channel=RetrievalChannel.SEMANTIC,
            )
            for row in rows
            if row.distance is not None
        ]


__all__ = ["JOB_TABLE", "PostgresJobCatalog", "row_to_job_fact"]
