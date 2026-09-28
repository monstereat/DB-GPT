"""SQLAlchemy persistence for UTC daily token quota accounting."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, Date, DateTime, Index, String, func

from dbgpt.storage.metadata import Model


class TokenQuotaDailyEntity(Model):
    """Aggregated token usage and outstanding reservations for one principal/day.

    ``quota_day_utc`` is the UTC calendar day selected when the reservation is
    created. The daily limit is supplied by policy at reservation time and is
    expressed in tokens (prompt plus completion); only accounting totals live
    in this table.
    """

    __tablename__ = "dbgpt_token_quota_daily"

    tenant_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), primary_key=True)
    quota_day_utc = Column(Date, primary_key=True)
    used_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
        server_default=func.now(),
    )


class TokenQuotaReservationEntity(Model):
    """Idempotency record for one model-call token reservation."""

    __tablename__ = "dbgpt_token_quota_reservation"
    __table_args__ = (
        Index(
            "idx_token_quota_reservation_bucket",
            "tenant_id",
            "user_id",
            "quota_day_utc",
        ),
        Index("idx_token_quota_reservation_state_created", "state", "created_at"),
    )

    reservation_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    quota_day_utc = Column(Date, nullable=False)
    reserved_tokens = Column(BigInteger, nullable=False)
    settled_tokens = Column(BigInteger, nullable=True)
    # pending / settled / released
    state = Column(String(16), nullable=False, default="pending")
    created_at = Column(
        DateTime, nullable=False, default=datetime.now, server_default=func.now()
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
        server_default=func.now(),
    )
