"""Atomic daily token quota reservation and settlement operations."""

import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from dbgpt.storage.metadata import BaseDao

from .models import TokenQuotaDailyEntity, TokenQuotaReservationEntity


class TokenQuotaExceededError(Exception):
    """Raised when a reservation would exceed the configured daily token limit."""


class TokenQuotaReservationConflictError(Exception):
    """Raised when a reservation ID is reused with incompatible state or values."""


@dataclass(frozen=True)
class TokenQuotaReservation:
    """Detached immutable reservation record returned by the DAO."""

    reservation_id: str
    tenant_id: str
    user_id: str
    quota_day_utc: date
    reserved_tokens: int
    settled_tokens: Optional[int]
    state: str


class TokenQuotaDao(BaseDao):
    """Persist per-user/per-tenant UTC-day reservations and usage.

    Token quantities are integer tokens, where usage means prompt plus
    completion tokens. Each model call reserves a preflight estimate before
    inference starts. If provider-reported usage exceeds the estimate or daily
    budget, settlement records the measured overage so later calls cannot use
    an understated balance; it cannot reverse provider usage already incurred.
    """

    _MAX_RETRIES = 5
    _STALE_RESERVATION_SECONDS = 15 * 60

    @staticmethod
    def utc_day(now: Optional[datetime] = None) -> date:
        """Return the UTC calendar date for a timezone-aware instant."""
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return instant.astimezone(timezone.utc).date()

    @staticmethod
    def _validate_principal(tenant_id: str, user_id: str) -> None:
        for field, value in (("tenant_id", tenant_id), ("user_id", user_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} must not be blank")

    @staticmethod
    def _validate_day(quota_day_utc: date) -> None:
        if isinstance(quota_day_utc, datetime) or not isinstance(quota_day_utc, date):
            raise ValueError("quota_day_utc must be a UTC calendar date")

    @staticmethod
    def _to_reservation(entity: TokenQuotaReservationEntity) -> TokenQuotaReservation:
        return TokenQuotaReservation(
            reservation_id=entity.reservation_id,
            tenant_id=entity.tenant_id,
            user_id=entity.user_id,
            quota_day_utc=entity.quota_day_utc,
            reserved_tokens=entity.reserved_tokens,
            settled_tokens=entity.settled_tokens,
            state=entity.state,
        )

    def reserve(
        self,
        tenant_id: str,
        user_id: str,
        amount_tokens: int,
        daily_limit_tokens: int,
        *,
        quota_day_utc: Optional[date] = None,
        reservation_id: Optional[str] = None,
    ) -> TokenQuotaReservation:
        """Atomically reserve tokens before one LLM call.

        ``daily_limit_tokens`` is the per-user/per-tenant preflight budget in
        prompt-plus-completion tokens; measured settlement may exceed it.
        ``quota_day_utc`` defaults to today's UTC date and is fixed for this
        reservation even if inference crosses midnight. Supplying
        ``reservation_id`` makes retries idempotent.
        """
        self._validate_principal(tenant_id, user_id)
        if not isinstance(amount_tokens, int) or isinstance(amount_tokens, bool):
            raise ValueError("amount_tokens must be an integer token count")
        if not isinstance(daily_limit_tokens, int) or isinstance(
            daily_limit_tokens, bool
        ):
            raise ValueError("daily_limit_tokens must be an integer token count")
        if amount_tokens <= 0:
            raise ValueError("amount_tokens must be greater than zero")
        if daily_limit_tokens <= 0:
            raise ValueError("daily_limit_tokens must be greater than zero")
        day = quota_day_utc or self.utc_day()
        self._validate_day(day)
        key = reservation_id or str(uuid.uuid4())
        if not key.strip() or len(key) > 64:
            raise ValueError("reservation_id must contain 1 to 64 characters")

        # A crashed worker cannot settle its reservation. Recover only this
        # principal's current-day reservations; earlier-day reservations no
        # longer consume today's budget.
        if self.get_reservation(key) is None:
            self.recover_stale_pending(
                tenant_id,
                user_id,
                day,
                stale_after_seconds=self._STALE_RESERVATION_SECONDS,
            )

        for attempt in range(self._MAX_RETRIES):
            try:
                with self.session() as session:
                    existing = session.get(TokenQuotaReservationEntity, key)
                    if existing is not None:
                        self._assert_same_reservation(
                            existing,
                            tenant_id,
                            user_id,
                            day,
                            amount_tokens,
                        )
                        return self._to_reservation(existing)

                    bucket = session.get(
                        TokenQuotaDailyEntity, (tenant_id, user_id, day)
                    )
                    if bucket is None:
                        # Concurrent first reservations race on the composite
                        # primary key. The loser retries the whole transaction.
                        session.add(
                            TokenQuotaDailyEntity(
                                tenant_id=tenant_id,
                                user_id=user_id,
                                quota_day_utc=day,
                                used_tokens=0,
                                reserved_tokens=0,
                            )
                        )
                        session.flush()

                    result = session.execute(
                        update(TokenQuotaDailyEntity)
                        .where(
                            and_(
                                TokenQuotaDailyEntity.tenant_id == tenant_id,
                                TokenQuotaDailyEntity.user_id == user_id,
                                TokenQuotaDailyEntity.quota_day_utc == day,
                                TokenQuotaDailyEntity.used_tokens
                                + TokenQuotaDailyEntity.reserved_tokens
                                + amount_tokens
                                <= daily_limit_tokens,
                            )
                        )
                        .values(
                            reserved_tokens=(
                                TokenQuotaDailyEntity.reserved_tokens + amount_tokens
                            ),
                            updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        )
                    )
                    if result.rowcount != 1:
                        raise TokenQuotaExceededError(
                            "daily token quota would be exceeded"
                        )

                    entity = TokenQuotaReservationEntity(
                        reservation_id=key,
                        tenant_id=tenant_id,
                        user_id=user_id,
                        quota_day_utc=day,
                        reserved_tokens=amount_tokens,
                        settled_tokens=None,
                        state="pending",
                    )
                    session.add(entity)
                    session.flush()
                    return self._to_reservation(entity)
            except TokenQuotaExceededError:
                raise
            except (IntegrityError, OperationalError):
                if attempt + 1 >= self._MAX_RETRIES:
                    raise
                # SQLite serializes writers; this short backoff also handles
                # unique-key races when several processes create the bucket.
                time.sleep(0.01 * (attempt + 1))
        raise RuntimeError("token quota reservation retry exhausted")

    @staticmethod
    def _assert_same_reservation(
        entity: TokenQuotaReservationEntity,
        tenant_id: str,
        user_id: str,
        quota_day_utc: date,
        amount_tokens: int,
    ) -> None:
        if (
            entity.tenant_id != tenant_id
            or entity.user_id != user_id
            or entity.quota_day_utc != quota_day_utc
            or entity.reserved_tokens != amount_tokens
        ):
            raise TokenQuotaReservationConflictError(
                "reservation_id was already used for a different reservation"
            )

    def get_reservation(self, reservation_id: str) -> Optional[TokenQuotaReservation]:
        """Return an immutable reservation snapshot, if present."""
        with self.session(commit=False) as session:
            entity = session.get(TokenQuotaReservationEntity, reservation_id)
            return self._to_reservation(entity) if entity is not None else None

    def heartbeat(self, reservation_id: str) -> bool:
        """Refresh the lease timestamp for an active pending reservation."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.session() as session:
            changed = session.execute(
                update(TokenQuotaReservationEntity)
                .where(
                    and_(
                        TokenQuotaReservationEntity.reservation_id == reservation_id,
                        TokenQuotaReservationEntity.state == "pending",
                    )
                )
                .values(updated_at=now)
            )
            return changed.rowcount == 1

    def recover_stale_pending(
        self,
        tenant_id: str,
        user_id: str,
        quota_day_utc: date,
        *,
        stale_after_seconds: int = _STALE_RESERVATION_SECONDS,
        now: Optional[datetime] = None,
        limit: int = 1000,
    ) -> int:
        """Settle expired pending reservations at their full reserved amount.

        A provider may have billed a request before its worker crashed, so
        recovery never releases budget. The conditional state/timestamp update
        makes recovery race-safe with settlement and active-worker heartbeats.
        """
        self._validate_principal(tenant_id, user_id)
        self._validate_day(quota_day_utc)
        if (
            not isinstance(stale_after_seconds, int)
            or isinstance(stale_after_seconds, bool)
            or stale_after_seconds <= 0
        ):
            raise ValueError("stale_after_seconds must be a positive integer")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        now_utc = instant.astimezone(timezone.utc).replace(tzinfo=None)
        cutoff = now_utc - timedelta(seconds=stale_after_seconds)
        recovered = 0
        with self.session() as session:
            candidates = session.execute(
                select(TokenQuotaReservationEntity)
                .where(
                    and_(
                        TokenQuotaReservationEntity.tenant_id == tenant_id,
                        TokenQuotaReservationEntity.user_id == user_id,
                        TokenQuotaReservationEntity.quota_day_utc == quota_day_utc,
                        TokenQuotaReservationEntity.state == "pending",
                        TokenQuotaReservationEntity.updated_at <= cutoff,
                    )
                )
                .order_by(TokenQuotaReservationEntity.updated_at)
                .limit(limit)
            ).scalars()
            for entity in candidates:
                changed = session.execute(
                    update(TokenQuotaReservationEntity)
                    .where(
                        and_(
                            TokenQuotaReservationEntity.reservation_id
                            == entity.reservation_id,
                            TokenQuotaReservationEntity.state == "pending",
                            TokenQuotaReservationEntity.updated_at <= cutoff,
                        )
                    )
                    .values(
                        state="settled",
                        settled_tokens=TokenQuotaReservationEntity.reserved_tokens,
                        updated_at=now_utc,
                    )
                )
                if changed.rowcount != 1:
                    continue
                bucket_changed = session.execute(
                    update(TokenQuotaDailyEntity)
                    .where(
                        and_(
                            TokenQuotaDailyEntity.tenant_id == tenant_id,
                            TokenQuotaDailyEntity.user_id == user_id,
                            TokenQuotaDailyEntity.quota_day_utc == quota_day_utc,
                            TokenQuotaDailyEntity.reserved_tokens
                            >= entity.reserved_tokens,
                        )
                    )
                    .values(
                        reserved_tokens=(
                            TokenQuotaDailyEntity.reserved_tokens
                            - entity.reserved_tokens
                        ),
                        used_tokens=(
                            TokenQuotaDailyEntity.used_tokens + entity.reserved_tokens
                        ),
                        updated_at=now_utc,
                    )
                )
                if bucket_changed.rowcount != 1:
                    raise TokenQuotaReservationConflictError(
                        "daily token quota bucket is missing or inconsistent"
                    )
                recovered += 1
        return recovered

    def settle(self, reservation_id: str, actual_tokens: int) -> TokenQuotaReservation:
        """Replace a pending reservation with measured prompt-plus-output usage.

        Repeating the same settlement is idempotent. If actual usage exceeds
        the estimate, it is still recorded; later reservations fail once the
        daily total is above the configured limit.
        """
        if not isinstance(actual_tokens, int) or isinstance(actual_tokens, bool):
            raise ValueError("actual_tokens must be an integer token count")
        if actual_tokens < 0:
            raise ValueError("actual_tokens must not be negative")
        with self.session() as session:
            entity = session.get(TokenQuotaReservationEntity, reservation_id)
            if entity is None:
                raise KeyError(reservation_id)
            if entity.state == "settled":
                if entity.settled_tokens != actual_tokens:
                    raise TokenQuotaReservationConflictError(
                        "reservation was already settled with different usage"
                    )
                return self._to_reservation(entity)
            if entity.state != "pending":
                raise TokenQuotaReservationConflictError(
                    f"cannot settle reservation in {entity.state!r} state"
                )
            changed = session.execute(
                update(TokenQuotaReservationEntity)
                .where(
                    and_(
                        TokenQuotaReservationEntity.reservation_id == reservation_id,
                        TokenQuotaReservationEntity.state == "pending",
                    )
                )
                .values(
                    state="settled",
                    settled_tokens=actual_tokens,
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise TokenQuotaReservationConflictError(
                    "reservation was settled or released concurrently"
                )
            bucket_changed = session.execute(
                update(TokenQuotaDailyEntity)
                .where(
                    and_(
                        TokenQuotaDailyEntity.tenant_id == entity.tenant_id,
                        TokenQuotaDailyEntity.user_id == entity.user_id,
                        TokenQuotaDailyEntity.quota_day_utc == entity.quota_day_utc,
                        TokenQuotaDailyEntity.reserved_tokens >= entity.reserved_tokens,
                    )
                )
                .values(
                    reserved_tokens=(
                        TokenQuotaDailyEntity.reserved_tokens - entity.reserved_tokens
                    ),
                    used_tokens=TokenQuotaDailyEntity.used_tokens + actual_tokens,
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            if bucket_changed.rowcount != 1:
                raise TokenQuotaReservationConflictError(
                    "daily token quota bucket is missing or inconsistent"
                )
            entity.state = "settled"
            entity.settled_tokens = actual_tokens
            return self._to_reservation(entity)

    def release(self, reservation_id: str) -> TokenQuotaReservation:
        """Release a pending reservation; repeated release is idempotent."""
        with self.session() as session:
            entity = session.get(TokenQuotaReservationEntity, reservation_id)
            if entity is None:
                raise KeyError(reservation_id)
            if entity.state == "released":
                return self._to_reservation(entity)
            if entity.state != "pending":
                raise TokenQuotaReservationConflictError(
                    f"cannot release reservation in {entity.state!r} state"
                )

            changed = session.execute(
                update(TokenQuotaReservationEntity)
                .where(
                    and_(
                        TokenQuotaReservationEntity.reservation_id == reservation_id,
                        TokenQuotaReservationEntity.state == "pending",
                    )
                )
                .values(
                    state="released",
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise TokenQuotaReservationConflictError(
                    "reservation was settled or released concurrently"
                )
            bucket_changed = session.execute(
                update(TokenQuotaDailyEntity)
                .where(
                    and_(
                        TokenQuotaDailyEntity.tenant_id == entity.tenant_id,
                        TokenQuotaDailyEntity.user_id == entity.user_id,
                        TokenQuotaDailyEntity.quota_day_utc == entity.quota_day_utc,
                        TokenQuotaDailyEntity.reserved_tokens >= entity.reserved_tokens,
                    )
                )
                .values(
                    reserved_tokens=(
                        TokenQuotaDailyEntity.reserved_tokens - entity.reserved_tokens
                    ),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )
            if bucket_changed.rowcount != 1:
                raise TokenQuotaReservationConflictError(
                    "daily token quota bucket is missing or inconsistent"
                )
            entity.state = "released"
            return self._to_reservation(entity)

    def get_daily_totals(
        self, tenant_id: str, user_id: str, quota_day_utc: date
    ) -> tuple[int, int]:
        """Return ``(used_tokens, reserved_tokens)`` for one UTC daily bucket."""
        self._validate_principal(tenant_id, user_id)
        self._validate_day(quota_day_utc)
        with self.session(commit=False) as session:
            bucket = session.get(
                TokenQuotaDailyEntity, (tenant_id, user_id, quota_day_utc)
            )
            if bucket is None:
                return 0, 0
            return int(bucket.used_tokens), int(bucket.reserved_tokens)
