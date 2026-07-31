from .service import (
    RecommendationRunService,
    assemble_candidates,
    assemble_recommendations,
    plan_run_input,
)
from .store import (
    CreateRunResult,
    IdempotencyConflictError,
    RecommendationProjection,
    RecommendationRecord,
    RecommendationRunStore,
    RunRecord,
    projection_to_card,
    projection_to_result,
    record_to_task_view,
)


def PostgresRecommendationRunStore(session_factory):
    """Legacy constructor kept for database integration tests and old callers."""
    from ..infrastructure.credit_store import PostgresCreditStore
    from ..infrastructure.recommendation_store import PostgresRecommendationStore

    return PostgresRecommendationStore(session_factory, PostgresCreditStore(session_factory))


__all__ = [
    "CreateRunResult",
    "IdempotencyConflictError",
    "RecommendationProjection",
    "RecommendationRecord",
    "RecommendationRunService",
    "RecommendationRunStore",
    "PostgresRecommendationRunStore",
    "RunRecord",
    "assemble_candidates",
    "assemble_recommendations",
    "plan_run_input",
    "projection_to_card",
    "projection_to_result",
    "record_to_task_view",
]
