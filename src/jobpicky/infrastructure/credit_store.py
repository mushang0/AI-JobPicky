from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..contracts import CreditUsage, ErrorCode
from ..errors import ApplicationError

CREDIT_ACCOUNT_TABLE = sa.table(
    "credit_account",
    sa.column("user_id", sa.String),
    sa.column("balance", sa.BigInteger),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

CREDIT_LEDGER_TABLE = sa.table(
    "credit_ledger",
    sa.column("id", sa.String),
    sa.column("user_id", sa.String),
    sa.column("entry_type", sa.String),
    sa.column("amount", sa.BigInteger),
    sa.column("reference_id", sa.String),
    sa.column("balance_after", sa.BigInteger),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

SIGNUP_BONUS = "SIGNUP_BONUS"
RECOMMENDATION_DEBIT = "RECOMMENDATION_DEBIT"
RECOMMENDATION_REFUND = "RECOMMENDATION_REFUND"


async def initialize_credits(
    session: AsyncSession,
    user_id: str,
    amount: int,
    *,
    now: datetime,
) -> None:
    await session.execute(
        sa.insert(CREDIT_ACCOUNT_TABLE).values(
            user_id=user_id,
            balance=amount,
            created_at=now,
            updated_at=now,
        )
    )
    if amount:
        await session.execute(
            sa.insert(CREDIT_LEDGER_TABLE).values(
                id=str(uuid4()),
                user_id=user_id,
                entry_type=SIGNUP_BONUS,
                amount=amount,
                reference_id=user_id,
                balance_after=amount,
                created_at=now,
            )
        )


class PostgresCreditStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_balance(self, user_id: str) -> int:
        async with self._session_factory() as session:
            balance = await session.scalar(
                sa.select(CREDIT_ACCOUNT_TABLE.c.balance).where(
                    CREDIT_ACCOUNT_TABLE.c.user_id == user_id
                )
            )
        if balance is None:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR,
                "credit account is missing",
                status_code=500,
            )
        return int(balance)

    async def charge_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        async with self._session_factory() as session, session.begin():
            return await self.charge_in_session(session, user_id, run_id, amount)

    async def refund_recommendation(
        self,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        async with self._session_factory() as session, session.begin():
            return await self.refund_in_session(session, user_id, run_id, amount)

    async def charge_in_session(
        self,
        session: AsyncSession,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        if amount <= 0:
            raise ValueError("credit charge amount must be positive")
        await self._lock_entry(session, user_id, run_id, RECOMMENDATION_DEBIT)
        existing = await self._entry(session, user_id, run_id, RECOMMENDATION_DEBIT)
        if existing is not None:
            if int(existing.amount) != -amount:
                raise ApplicationError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "credit debit amount differs from the existing entry",
                    status_code=409,
                )
            return CreditUsage(cost=amount, refunded=False, net_spent=amount)

        now = datetime.now(UTC)
        balance = await session.scalar(
            sa.update(CREDIT_ACCOUNT_TABLE)
            .where(
                CREDIT_ACCOUNT_TABLE.c.user_id == user_id,
                CREDIT_ACCOUNT_TABLE.c.balance >= amount,
            )
            .values(
                balance=CREDIT_ACCOUNT_TABLE.c.balance - amount,
                updated_at=now,
            )
            .returning(CREDIT_ACCOUNT_TABLE.c.balance)
        )
        if balance is None:
            raise ApplicationError(
                ErrorCode.INSUFFICIENT_CREDITS,
                "insufficient credits",
                status_code=409,
            )
        await session.execute(
            sa.insert(CREDIT_LEDGER_TABLE).values(
                id=str(uuid4()),
                user_id=user_id,
                entry_type=RECOMMENDATION_DEBIT,
                amount=-amount,
                reference_id=run_id,
                balance_after=balance,
                created_at=now,
            )
        )
        return CreditUsage(cost=amount, refunded=False, net_spent=amount)

    async def refund_in_session(
        self,
        session: AsyncSession,
        user_id: str,
        run_id: str,
        amount: int,
    ) -> CreditUsage:
        if amount <= 0:
            raise ValueError("credit refund amount must be positive")
        await self._lock_entry(session, user_id, run_id, RECOMMENDATION_REFUND)
        existing = await self._entry(session, user_id, run_id, RECOMMENDATION_REFUND)
        if existing is not None:
            if int(existing.amount) != amount:
                raise ApplicationError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "credit refund amount differs from the existing entry",
                    status_code=409,
                )
            return CreditUsage(cost=amount, refunded=True, net_spent=0)

        debit = await self._entry(session, user_id, run_id, RECOMMENDATION_DEBIT)
        if debit is None or int(debit.amount) != -amount:
            raise ApplicationError(
                ErrorCode.CONFLICT,
                "recommendation debit does not exist",
                status_code=409,
            )
        now = datetime.now(UTC)
        balance = await session.scalar(
            sa.update(CREDIT_ACCOUNT_TABLE)
            .where(CREDIT_ACCOUNT_TABLE.c.user_id == user_id)
            .values(
                balance=CREDIT_ACCOUNT_TABLE.c.balance + amount,
                updated_at=now,
            )
            .returning(CREDIT_ACCOUNT_TABLE.c.balance)
        )
        if balance is None:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR,
                "credit account is missing",
                status_code=500,
            )
        await session.execute(
            sa.insert(CREDIT_LEDGER_TABLE).values(
                id=str(uuid4()),
                user_id=user_id,
                entry_type=RECOMMENDATION_REFUND,
                amount=amount,
                reference_id=run_id,
                balance_after=balance,
                created_at=now,
            )
        )
        return CreditUsage(cost=amount, refunded=True, net_spent=0)

    @staticmethod
    async def _lock_entry(
        session: AsyncSession,
        user_id: str,
        run_id: str,
        entry_type: str,
    ) -> None:
        await session.execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"credit:{user_id}:{run_id}:{entry_type}"},
        )

    @staticmethod
    async def _entry(
        session: AsyncSession,
        user_id: str,
        run_id: str,
        entry_type: str,
    ) -> sa.RowMapping | None:
        result = await session.execute(
            sa.select(CREDIT_LEDGER_TABLE).where(
                CREDIT_LEDGER_TABLE.c.user_id == user_id,
                CREDIT_LEDGER_TABLE.c.reference_id == run_id,
                CREDIT_LEDGER_TABLE.c.entry_type == entry_type,
            )
        )
        return result.mappings().one_or_none()


__all__ = [
    "CREDIT_ACCOUNT_TABLE",
    "CREDIT_LEDGER_TABLE",
    "PostgresCreditStore",
    "RECOMMENDATION_DEBIT",
    "RECOMMENDATION_REFUND",
    "SIGNUP_BONUS",
    "initialize_credits",
]
