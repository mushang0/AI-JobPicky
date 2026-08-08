"""Bootstrap Feishu OAuth once or incrementally ingest the Bitable every day."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import secrets
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from itertools import islice
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from jobpicky.collection.feishu_bitable import (
    FeishuApiError,
    FeishuBitableClient,
    FeishuBitableConfig,
    FeishuBitableSource,
    FeishuRecord,
)
from jobpicky.collection.pipeline import run_pipeline_by_source, source_id_for_entry
from jobpicky.collection.spreadsheet import SpreadsheetRow
from jobpicky.config import Settings
from jobpicky.infrastructure.database import create_engine, create_session_factory
from jobpicky.infrastructure.feishu_auth import (
    FeishuAuthError,
    FeishuOAuthClient,
    FeishuTokenManager,
    FeishuTokenStore,
    open_authorization_url,
    wait_for_local_authorization_code,
)
from jobpicky.infrastructure.feishu_sync_state import (
    PostgresFeishuSyncStateStore,
    should_process,
)
from jobpicky.infrastructure.job_catalog import PostgresJobCatalog

_DEFAULT_REDIRECT_URI = "http://localhost:8787/callback"
_DEFAULT_TOKEN_FILE = "~/.config/jobpicky/feishu-token.json"
_DEFAULT_LOCK_FILE = "~/.cache/jobpicky/feishu.lock"
_DEFAULT_SCOPE = "bitable:app:readonly offline_access"


@dataclass(frozen=True, slots=True)
class FeishuScriptConfig:
    app_id: str
    app_secret: str
    bitable: FeishuBitableConfig
    redirect_uri: str
    token_file: Path
    lock_file: Path
    scope: str

    @classmethod
    def from_env(cls) -> FeishuScriptConfig:
        return cls(
            app_id=_required("JOBPICKY_FEISHU_APP_ID"),
            app_secret=_required("JOBPICKY_FEISHU_APP_SECRET"),
            bitable=FeishuBitableConfig(
                app_token=_required("JOBPICKY_FEISHU_APP_TOKEN"),
                table_id=_required("JOBPICKY_FEISHU_TABLE_ID"),
                view_id=_optional("JOBPICKY_FEISHU_VIEW_ID"),
                since_date=_read_date(
                    os.environ.get("JOBPICKY_FEISHU_SINCE_DATE", "2026-06-20"),
                    "JOBPICKY_FEISHU_SINCE_DATE",
                ),
            ),
            redirect_uri=os.environ.get(
                "JOBPICKY_FEISHU_REDIRECT_URI", _DEFAULT_REDIRECT_URI
            ).strip(),
            token_file=Path(
                os.environ.get("JOBPICKY_FEISHU_TOKEN_FILE", _DEFAULT_TOKEN_FILE)
            ).expanduser(),
            lock_file=Path(
                os.environ.get("JOBPICKY_FEISHU_LOCK_FILE", _DEFAULT_LOCK_FILE)
            ).expanduser(),
            scope=os.environ.get("JOBPICKY_FEISHU_OAUTH_SCOPE", _DEFAULT_SCOPE).strip(),
        )


@dataclass
class _RecordOutcome:
    failures: list[str]
    item_count: int = 0


def _job_record_id(job: object) -> str | None:
    metadata = getattr(job, "metadata", None)
    if isinstance(metadata, dict):
        record_id = metadata.get("feishu_record_id")
        if isinstance(record_id, str) and record_id:
            return record_id
    source_ref = getattr(job, "source_ref", None)
    if isinstance(source_ref, str) and source_ref.startswith("feishu-record:"):
        return source_ref.removeprefix("feishu-record:") or None
    return None


class SingleProcessLock:
    def __init__(self, path: Path) -> None:
        self._path = path.expanduser()
        self._file: TextIO | None = None

    def __enter__(self) -> SingleProcessLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file = self._path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            file.close()
            raise RuntimeError(f"another Feishu sync is already running: {self._path}") from exc
        self._file = file
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if (file := self._file) is not None:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
            file.close()
            self._file = None


def _auth_client(config: FeishuScriptConfig) -> FeishuOAuthClient:
    return FeishuOAuthClient(
        config.app_id,
        config.app_secret,
        redirect_uri=config.redirect_uri,
    )


def _token_manager(config: FeishuScriptConfig) -> FeishuTokenManager:
    return FeishuTokenManager(
        _auth_client(config),
        FeishuTokenStore(config.token_file),
    )


def run_auth(config: FeishuScriptConfig, *, open_browser: bool, timeout_seconds: int) -> None:
    oauth = _auth_client(config)
    manager = _token_manager(config)
    state = secrets.token_urlsafe(24)
    url = oauth.authorization_url(state=state, scopes=config.scope)
    print("请在浏览器中完成飞书授权。", file=sys.stderr)

    def open_or_print_url() -> None:
        if open_browser:
            open_authorization_url(url)
        else:
            print(f"请手动打开：{url}")

    code = wait_for_local_authorization_code(
        config.redirect_uri,
        expected_state=state,
        timeout_seconds=timeout_seconds,
        on_ready=open_or_print_url,
    )
    bundle = manager.exchange_and_save(code)
    print(f"授权成功，token 已保存到：{config.token_file}")
    print(f"access_token 有效期约 {max(0, int(bundle.access_expires_at - _now()))} 秒")
    print("开始读取字段和最多 5 条记录进行连通性检查……")
    client = FeishuBitableClient(bundle.access_token)
    _print_smoke_summary(client, config)


def _print_smoke_summary(client: FeishuBitableClient, config: FeishuScriptConfig) -> None:
    fields = client.list_fields(
        config.bitable.app_token,
        config.bitable.table_id,
    )
    field_summary = [
        (item.get("field_name"), item.get("type"))
        for item in fields
        if item.get("field_name") is not None
    ]
    records = list(
        islice(
            client.iter_records(
                config.bitable.app_token,
                config.bitable.table_id,
                view_id=config.bitable.view_id,
                page_size=5,
            ),
            5,
        )
    )
    print(f"字段数量：{len(fields)}")
    print(f"字段名和类型：{field_summary}")
    print(f"读取记录数量：{len(records)}")
    print("记录 ID：", [record.record_id for record in records])


async def run_sync(
    config: FeishuScriptConfig,
    *,
    limit: int | None,
    reset: bool = False,
) -> None:
    manager = _token_manager(config)
    access_token = manager.get_access_token()
    try:
        records = _fetch_records(config, access_token, limit=limit)
    except FeishuApiError as exc:
        if exc.status_code != 401:
            raise
        access_token = manager.get_access_token(force_refresh=True)
        records = _fetch_records(config, access_token, limit=limit)

    source = FeishuBitableSource(config.bitable)
    engine = create_engine(Settings.from_env().database_url)
    session_factory = create_session_factory(engine)
    state_store = PostgresFeishuSyncStateStore(session_factory)
    catalog = PostgresJobCatalog(session_factory)
    unique_records = _unique_records(records)
    if reset:
        source = FeishuBitableSource(config.bitable)
        has_eligible_record = any(
            (row := source.row_from_record(record, row_number)) is not None
            and source.row_is_after_cutoff(row)
            and bool(row.apply_links)
            for row_number, record in enumerate(unique_records, start=1)
        )
        if not has_eligible_record:
            await engine.dispose()
            raise RuntimeError(
                "reset aborted: no eligible Feishu record after the configured cutoff"
            )
        await catalog.reset_development_data()
        await state_store.reset(config.bitable.app_token, config.bitable.table_id)
        print("reset=development-job-data-and-feishu-sync-state")
    run_id = f"feishu-{uuid4()}"
    counts: Counter[str] = Counter()

    async def save_state(
        record: FeishuRecord,
        record_hash: str,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        await state_store.save(
            app_token=config.bitable.app_token,
            table_id=config.bitable.table_id,
            record_id=record.record_id,
            record_hash=record_hash,
            last_modified_time=record.last_modified_time,
            status=status,
            last_error=last_error,
        )

    try:
        states = await state_store.get_many(
            config.bitable.app_token,
            config.bitable.table_id,
            [record.record_id for record in unique_records],
        )
        eligible: list[tuple[FeishuRecord, str, SpreadsheetRow]] = []
        for row_number, record in enumerate(unique_records, start=1):
            record_hash = source.record_hash(record)
            state = states.get(record.record_id)
            if not should_process(state, record_hash):
                counts["unchanged"] += 1
                continue

            try:
                row = source.row_from_record(record, row_number)
                if row is None:
                    await save_state(
                        record,
                        record_hash,
                        status="SKIPPED",
                        last_error="row is empty or an instruction row",
                    )
                    counts["skipped"] += 1
                    continue
                if not source.row_is_after_cutoff(row):
                    await save_state(
                        record,
                        record_hash,
                        status="SKIPPED",
                        last_error="updated_at is missing or not after the configured cutoff",
                    )
                    counts["skipped"] += 1
                    continue
                if not row.apply_links:
                    await save_state(
                        record,
                        record_hash,
                        status="SKIPPED",
                        last_error="no supported application link",
                    )
                    counts["skipped"] += 1
                    continue
                eligible.append((record, record_hash, row))
            except Exception as exc:  # noqa: BLE001 - isolate one record from the batch
                await save_state(
                    record,
                    record_hash,
                    status="FAILED",
                    last_error=f"{type(exc).__name__}: {exc}"[:2000],
                )
                counts["failed"] += 1

        outcomes = {record.record_id: _RecordOutcome([]) for record, _record_hash, _row in eligible}
        rows_by_number = {
            row.row_number: (record, record_hash) for record, record_hash, row in eligible
        }
        source_record_ids: dict[str, set[str]] = {}
        for record, _record_hash, row in eligible:
            if row.company_name is None:
                continue
            for url in row.apply_links:
                source_record_ids.setdefault(source_id_for_entry(row.company_name, url), set()).add(
                    record.record_id
                )
        try:
            pipeline_results = run_pipeline_by_source([row for _record, _hash, row in eligible])
        except Exception as exc:  # noqa: BLE001 - keep a batch parser failure state-local
            error = f"{type(exc).__name__}: {exc}"
            for outcome in outcomes.values():
                outcome.failures.append(error)
            pipeline_results = []

        for result in pipeline_results:
            result_record_ids = set(source_record_ids.get(result.batch.source_id, ()))
            result_record_ids.update(
                record_id
                for record_id in (_job_record_id(item) for item in result.batch.items)
                if record_id in outcomes
            )
            for failure in result.unsupported:
                record_info = rows_by_number.get(failure.row_number)
                if record_info is None:
                    continue
                record, _record_hash = record_info
                result_record_ids.add(record.record_id)
                outcomes[record.record_id].failures.append(f"{failure.link_type}: {failure.reason}")
            if not result.batch.items:
                continue
            try:
                ingestion = await catalog.ingest(run_id, result.batch)
            except Exception as exc:  # noqa: BLE001 - isolate one batch write failure
                error = f"{type(exc).__name__}: {exc}"
                for record_id in result_record_ids:
                    outcomes[record_id].failures.append(error)
                continue
            counts["created"] += ingestion.created_count
            counts["updated"] += ingestion.updated_count
            counts["unchanged_jobs"] += ingestion.unchanged_count
            for record_id in result_record_ids:
                outcomes[record_id].item_count += 1

        for record, record_hash, _row in eligible:
            outcome = outcomes[record.record_id]
            status = (
                "FAILED" if outcome.failures else ("SUCCEEDED" if outcome.item_count else "SKIPPED")
            )
            await save_state(
                record,
                record_hash,
                status=status,
                last_error="; ".join(outcome.failures)[:2000] if outcome.failures else None,
            )
            counts[status.lower()] += 1
    finally:
        await engine.dispose()

    print(
        "sync complete "
        f"records={len(unique_records)} succeeded={counts['succeeded']} "
        f"failed={counts['failed']} skipped={counts['skipped']} unchanged={counts['unchanged']} "
        f"created={counts['created']} updated={counts['updated']} "
        f"unchanged_jobs={counts['unchanged_jobs']}"
    )


def _fetch_records(
    config: FeishuScriptConfig,
    access_token: str,
    *,
    limit: int | None,
) -> list[FeishuRecord]:
    client = FeishuBitableClient(access_token)
    source = FeishuBitableSource(config.bitable)
    iterator = client.iter_records(
        config.bitable.app_token,
        config.bitable.table_id,
        view_id=config.bitable.view_id,
        # Feishu ignores view_id when sort is present; the explicit date order
        # is what makes the cutoff stop safe.
        sort=[
            {
                "field_name": config.bitable.field_map["updated_at"],
                "desc": True,
            }
        ],
        page_size=min(limit or 500, 500),
    )
    records: list[FeishuRecord] = []
    for record in iterator:
        records.append(record)
        if limit is not None and len(records) >= limit:
            break
        if source.record_is_at_or_before_cutoff(record):
            break
    return records


def _unique_records(records: list[FeishuRecord]) -> list[FeishuRecord]:
    by_id: dict[str, FeishuRecord] = {}
    for record in records:
        by_id[record.record_id] = record
    return list(by_id.values())


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def _read_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _now() -> float:
    return time.time()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    auth_parser = subparsers.add_parser("auth", help="run the one-time browser OAuth bootstrap")
    auth_parser.add_argument("--no-browser", action="store_true")
    auth_parser.add_argument("--timeout", type=int, default=180)
    sync_parser = subparsers.add_parser("sync", help="refresh the token and ingest changed records")
    sync_parser.add_argument("--limit", type=int, default=None)
    sync_parser.add_argument(
        "--reset",
        action="store_true",
        help="读取飞书记录成功后清空开发岗位数据并强制全量重灌",
    )
    args = parser.parse_args()
    try:
        config = FeishuScriptConfig.from_env()
        if args.command == "auth":
            run_auth(config, open_browser=not args.no_browser, timeout_seconds=args.timeout)
        else:
            if args.limit is not None and args.limit < 1:
                parser.error("--limit must be at least 1")
            if args.reset and Settings.from_env().environment not in {"development", "dev", "test"}:
                parser.error("--reset 仅允许在 development、dev 或 test 环境使用")
            with SingleProcessLock(config.lock_file):
                asyncio.run(run_sync(config, limit=args.limit, reset=args.reset))
        return 0
    except (FeishuApiError, FeishuAuthError, RuntimeError, ValueError) as exc:
        print(f"feishu command failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
