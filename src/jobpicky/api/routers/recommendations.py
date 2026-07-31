from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from ...contracts import (
    Page,
    RecommendationCardView,
    RecommendationFeedbackRequest,
    RecommendationFeedbackView,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunRequest,
    RecommendationSort,
    RecommendationTaskView,
)
from ...orchestration import RecommendationRunService
from ..dependencies import RequiredUser

router = APIRouter(prefix="/api/v1/user", tags=["recommendations"])


def get_recommendation_service(request: Request) -> RecommendationRunService:
    return cast(RecommendationRunService, request.app.state.recommendation_service)


RecommendationServiceDependency = Annotated[
    RecommendationRunService,
    Depends(get_recommendation_service),
]


@router.get("/recommendations", response_model=Page[RecommendationCardView])
async def list_recommendations(
    user: RequiredUser,
    service: RecommendationServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
    sort_by: Annotated[
        RecommendationSort,
        Query(alias="sort"),
    ] = RecommendationSort.RECOMMENDED_AT_DESC,
) -> Page[RecommendationCardView]:
    return await service.list_recommendations(user.id, page, page_size, sort_by)


@router.get("/recommendation-runs", response_model=Page[RecommendationTaskView])
async def list_recommendation_runs(
    user: RequiredUser,
    service: RecommendationServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[RecommendationTaskView]:
    return await service.list_runs(user.id, page, page_size)


@router.post(
    "/recommendation-runs",
    response_model=RecommendationRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_recommendation_run(
    body: RecommendationRunRequest,
    user: RequiredUser,
    service: RecommendationServiceDependency,
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[\x20-\x7e]+$",
        ),
    ],
) -> RecommendationRunAccepted:
    return await service.start(user.id, body.extra_request, idempotency_key)


@router.get(
    "/recommendation-runs/{run_id}",
    response_model=RecommendationTaskView,
)
async def get_recommendation_run(
    run_id: Annotated[str, Path(min_length=1)],
    user: RequiredUser,
    service: RecommendationServiceDependency,
) -> RecommendationTaskView:
    return await service.get_run(user.id, run_id)


@router.get(
    "/recommendation-runs/{run_id}/results",
    response_model=Page[RecommendationResultView],
)
async def get_recommendation_results(
    run_id: Annotated[str, Path(min_length=1)],
    user: RequiredUser,
    service: RecommendationServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> Page[RecommendationResultView]:
    return await service.get_results(user.id, run_id, page, page_size)


@router.put(
    "/recommendations/{recommendation_id}/feedback",
    response_model=RecommendationFeedbackView,
)
async def update_recommendation_feedback(
    recommendation_id: Annotated[str, Path(min_length=1)],
    body: RecommendationFeedbackRequest,
    user: RequiredUser,
    service: RecommendationServiceDependency,
) -> RecommendationFeedbackView:
    return await service.update_feedback(user.id, recommendation_id, body.feedback)


@router.delete(
    "/recommendations/{recommendation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_recommendation(
    recommendation_id: Annotated[str, Path(min_length=1)],
    user: RequiredUser,
    service: RecommendationServiceDependency,
) -> Response:
    await service.delete_recommendation(user.id, recommendation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["RecommendationServiceDependency", "get_recommendation_service", "router"]
