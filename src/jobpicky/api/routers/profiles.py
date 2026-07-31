from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from ...contracts import CurrentProfileView, ProfileSaveRequest, ProfileSnapshot
from ..dependencies import ProfileServiceDependency, RequiredUser

router = APIRouter(prefix="/api/v1/user/profiles", tags=["profiles"])

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[\x20-\x7e]+$",
    ),
]


@router.get("/current", response_model=CurrentProfileView)
async def get_current_profile(
    user: RequiredUser,
    service: ProfileServiceDependency,
) -> CurrentProfileView:
    return _to_view(await service.get_current(user.id))


@router.put(
    "/current",
    response_model=CurrentProfileView,
    responses={status.HTTP_201_CREATED: {"model": CurrentProfileView}},
)
async def save_current_profile(
    payload: ProfileSaveRequest,
    response: Response,
    user: RequiredUser,
    service: ProfileServiceDependency,
    idempotency_key: IdempotencyKey,
) -> CurrentProfileView:
    snapshot = await service.save_current(user.id, payload, idempotency_key)
    if payload.base_version is None and snapshot.version == 1:
        response.status_code = status.HTTP_201_CREATED
    return _to_view(snapshot)


def _to_view(snapshot: ProfileSnapshot) -> CurrentProfileView:
    return CurrentProfileView.model_validate(snapshot.model_dump(exclude={"user_id"}))


__all__ = ["router"]
