from jobpicky.infrastructure.feishu_sync_state import FeishuSyncState, should_process


def _state(*, record_hash: str = "hash-1", status: str = "SUCCEEDED") -> FeishuSyncState:
    return FeishuSyncState(
        record_id="rec-1",
        record_hash=record_hash,
        last_modified_time=None,
        last_processed_at=None,
        status=status,
        last_error=None,
    )


def test_sync_state_processes_new_changed_and_failed_records() -> None:
    assert should_process(None, "hash-1")
    assert not should_process(_state(), "hash-1")
    assert should_process(_state(), "hash-2")
    assert should_process(_state(status="FAILED"), "hash-1")
