from __future__ import annotations

from typing import Protocol

from ..contracts import CreditSummary, CreditUsage


class CreditStore(Protocol):
    async def get_balance(self, user_id: str) -> int: ...

    async def charge_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage: ...

    async def refund_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage: ...


class CreditService:
    def __init__(self, store: CreditStore, recommendation_cost: int) -> None:
        self._store = store
        self._recommendation_cost = recommendation_cost

    async def get_summary(self, user_id: str) -> CreditSummary:
        return CreditSummary(
            balance=await self._store.get_balance(user_id),
            recommendation_cost=self._recommendation_cost,
        )

    async def charge_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        return await self._store.charge_recommendation(user_id, run_id, amount)

    async def refund_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        return await self._store.refund_recommendation(user_id, run_id, amount)


__all__ = ["CreditService", "CreditStore"]
