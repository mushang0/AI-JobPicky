from __future__ import annotations

from fastapi import APIRouter

from ...contracts import CreditSummary
from ..dependencies import CreditServiceDependency, RequiredUser

router = APIRouter(prefix="/api/v1/user", tags=["credits"])


@router.get("/credits", response_model=CreditSummary)
async def get_credits(
    user: RequiredUser,
    service: CreditServiceDependency,
) -> CreditSummary:
    return await service.get_summary(user.id)


__all__ = ["router"]
