from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Header, Response, UploadFile, status

from ...contracts import (
    CurrentProfileView,
    ErrorBody,
    ProfileImportView,
    ProfileSaveRequest,
    ProfileSnapshot,
)
from ..dependencies import ProfileServiceDependency, RequiredUser

router = APIRouter(prefix="/api/v1/user", tags=["profiles"])

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[\x20-\x7e]+$",
    ),
]


@router.get("/profiles/current", response_model=CurrentProfileView)
async def get_current_profile(
    user: RequiredUser,
    service: ProfileServiceDependency,
) -> CurrentProfileView:
    return _to_view(await service.get_current(user.id))


@router.put(
    "/profiles/current",
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


@router.post(
    "/profile-imports",
    response_model=ProfileImportView,
    responses={
        422: {
            "model": ErrorBody,
            "description": "Resume cannot be rendered or exceeds the PDF page limit",
        },
        413: {"model": ErrorBody, "description": "Resume file is too large"},
        415: {"model": ErrorBody, "description": "Resume format is unsupported"},
        502: {"model": ErrorBody, "description": "Model output is invalid"},
        503: {"model": ErrorBody, "description": "Profile parser is unavailable"},
    },
)
async def import_resume(
    file: Annotated[
        UploadFile,
        File(description="PDF (maximum 4 pages), DOCX, TXT, or Markdown resume; maximum 10 MiB"),
    ],
    user: RequiredUser,
    service: ProfileServiceDependency,
) -> ProfileImportView:
    filename = file.filename or ""
    content_type = file.content_type
    try:
        content = await file.read(service.import_max_bytes + 1)
    finally:
        await file.close()
    return await service.import_resume(user.id, filename, content_type, content)


def _to_view(snapshot: ProfileSnapshot) -> CurrentProfileView:
    return CurrentProfileView.model_validate(snapshot.model_dump(exclude={"user_id"}))


__all__ = ["router"]
