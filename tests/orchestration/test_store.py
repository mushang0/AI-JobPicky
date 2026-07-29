from sqlalchemy.exc import IntegrityError

from jobpicky.orchestration.store import (
    _IDEMPOTENCY_INDEX_NAME,
    _is_idempotency_conflict,
)


class DriverError(Exception):
    def __init__(self, constraint_name: str | None) -> None:
        super().__init__()
        self.constraint_name = constraint_name


def _integrity_error(constraint_name: str | None) -> IntegrityError:
    return IntegrityError(
        "INSERT INTO recommendation_run",
        {},
        DriverError(constraint_name),
    )


def test_only_idempotency_unique_violation_is_classified_as_replay_conflict() -> None:
    assert _is_idempotency_conflict(_integrity_error(_IDEMPOTENCY_INDEX_NAME))
    assert not _is_idempotency_conflict(_integrity_error("recommendation_run_pkey"))
    assert not _is_idempotency_conflict(_integrity_error(None))
