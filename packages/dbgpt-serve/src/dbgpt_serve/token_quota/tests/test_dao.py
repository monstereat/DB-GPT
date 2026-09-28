"""SQLite contract tests for token quota reservations."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Date, String

from dbgpt.storage.metadata import db
from dbgpt_serve.token_quota.models.dao import (
    TokenQuotaDao,
    TokenQuotaExceededError,
    TokenQuotaReservationConflictError,
)
from dbgpt_serve.token_quota.models.models import (
    TokenQuotaDailyEntity,
    TokenQuotaReservationEntity,
)

QUOTA_DAY = date(2026, 9, 25)
SCHEMA_PATHS = (
    "assets/schema/dbgpt.sql",
    "assets/schema/upgrade/v0_8_2/upgrade_to_v0.8.2.sql",
    "assets/schema/upgrade/v0_8_2/v0.8.2.sql",
)


@pytest.fixture(autouse=True)
def setup_database():
    db.init_db("sqlite:///:memory:")
    db.create_all()
    yield


@pytest.fixture
def dao() -> TokenQuotaDao:
    return TokenQuotaDao()


def test_models_define_token_units_and_utc_bucket_key():
    daily = TokenQuotaDailyEntity.__table__
    reservation = TokenQuotaReservationEntity.__table__

    assert daily.name == "dbgpt_token_quota_daily"
    assert set(daily.primary_key.columns.keys()) == {
        "tenant_id",
        "user_id",
        "quota_day_utc",
    }
    assert isinstance(daily.c.tenant_id.type, String)
    assert isinstance(daily.c.user_id.type, String)
    assert isinstance(daily.c.quota_day_utc.type, Date)
    assert isinstance(daily.c.used_tokens.type, BigInteger)
    assert isinstance(daily.c.reserved_tokens.type, BigInteger)
    assert reservation.name == "dbgpt_token_quota_reservation"
    assert reservation.c.reservation_id.primary_key
    assert reservation.c.reserved_tokens.type.python_type is int
    assert reservation.c.settled_tokens.type.python_type is int


def test_mysql_schema_contract_includes_both_token_accounting_tables():
    repo_root = Path(__file__).resolve().parents[6]
    for relative_path in SCHEMA_PATHS:
        schema = (repo_root / relative_path).read_text()
        assert "CREATE TABLE IF NOT EXISTS `dbgpt_token_quota_daily`" in schema
        assert "CREATE TABLE IF NOT EXISTS `dbgpt_token_quota_reservation`" in schema
        assert "`quota_day_utc` date NOT NULL" in schema
        assert "`used_tokens` bigint NOT NULL DEFAULT 0" in schema
        assert "`reserved_tokens` bigint NOT NULL" in schema
        assert "prompt plus completion" in schema


def test_reserve_enforces_limit_across_used_and_outstanding_tokens(dao):
    first = dao.reserve(
        "tenant-a",
        "alice",
        7,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="first",
    )
    assert first.state == "pending"

    with pytest.raises(TokenQuotaExceededError):
        dao.reserve(
            "tenant-a",
            "alice",
            4,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="over-limit",
        )

    dao.settle("first", 6)
    with pytest.raises(TokenQuotaExceededError):
        dao.reserve(
            "tenant-a",
            "alice",
            5,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="over-used-limit",
        )

    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (6, 0)


def test_settlement_records_usage_above_preflight_budget(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        8,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="provider-overage",
    )

    settled = dao.settle("provider-overage", 12)

    assert settled.settled_tokens == 12
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (12, 0)
    with pytest.raises(TokenQuotaExceededError):
        dao.reserve(
            "tenant-a",
            "alice",
            1,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="after-overage",
        )


def test_daily_bucket_isolated_by_tenant_user_and_utc_day(dao):
    dao.reserve("tenant-a", "alice", 5, 5, quota_day_utc=QUOTA_DAY)

    assert (
        dao.reserve("tenant-a", "bob", 5, 5, quota_day_utc=QUOTA_DAY).state == "pending"
    )
    assert (
        dao.reserve("tenant-b", "alice", 5, 5, quota_day_utc=QUOTA_DAY).state
        == "pending"
    )
    assert (
        dao.reserve("tenant-a", "alice", 5, 5, quota_day_utc=date(2026, 9, 26)).state
        == "pending"
    )


def test_settle_is_idempotent_and_releases_unused_reserved_tokens(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        10,
        20,
        quota_day_utc=QUOTA_DAY,
        reservation_id="settle-me",
    )

    settled = dao.settle("settle-me", 7)
    assert (settled.state, settled.settled_tokens) == ("settled", 7)
    assert dao.settle("settle-me", 7) == settled
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (7, 0)

    with pytest.raises(TokenQuotaReservationConflictError):
        dao.settle("settle-me", 8)


def test_release_is_idempotent_and_returns_capacity(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        10,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="release-me",
    )

    released = dao.release("release-me")
    assert released.state == "released"
    assert dao.release("release-me") == released
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (0, 0)
    assert (
        dao.reserve("tenant-a", "alice", 10, 10, quota_day_utc=QUOTA_DAY).state
        == "pending"
    )


def test_reservation_idempotency_checks_identity_amount_and_state(dao):
    pending = dao.reserve(
        "tenant-a",
        "alice",
        3,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="retry-me",
    )
    assert (
        dao.reserve(
            "tenant-a",
            "alice",
            3,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="retry-me",
        )
        == pending
    )
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (0, 3)

    with pytest.raises(TokenQuotaReservationConflictError):
        dao.reserve(
            "tenant-b",
            "alice",
            3,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="retry-me",
        )
    with pytest.raises(TokenQuotaReservationConflictError):
        dao.reserve(
            "tenant-a",
            "alice",
            4,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="retry-me",
        )


def test_overrun_is_recorded_and_blocks_later_reservations(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        4,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="too-small-bound",
    )

    dao.settle("too-small-bound", 5)

    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (5, 0)
    assert dao.get_reservation("too-small-bound").state == "settled"
    with pytest.raises(TokenQuotaExceededError):
        dao.reserve(
            "tenant-a",
            "alice",
            6,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="after-overrun",
        )


def test_utc_day_is_derived_from_timezone_aware_instant(dao):
    assert dao.utc_day(datetime(2026, 9, 25, 16, 30, tzinfo=timezone.utc)) == date(
        2026, 9, 25
    )
    assert dao.utc_day(datetime.fromisoformat("2026-09-26T00:30:00+08:00")) == date(
        2026, 9, 25
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        dao.utc_day(datetime(2026, 9, 25, 12, 0))


def test_stale_reservation_recovery_charges_full_reserved_amount(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        9,
        20,
        quota_day_utc=QUOTA_DAY,
        reservation_id="crashed-call",
    )
    now = datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc)
    with dao.session() as session:
        entity = session.get(TokenQuotaReservationEntity, "crashed-call")
        entity.updated_at = datetime(2026, 9, 25, 11, 0)

    recovered = dao.recover_stale_pending(
        "tenant-a",
        "alice",
        QUOTA_DAY,
        stale_after_seconds=900,
        now=now,
    )

    reservation = dao.get_reservation("crashed-call")
    assert recovered == 1
    assert (reservation.state, reservation.settled_tokens) == ("settled", 9)
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (9, 0)
    assert (
        dao.recover_stale_pending(
            "tenant-a", "alice", QUOTA_DAY, stale_after_seconds=900, now=now
        )
        == 0
    )


def test_reservation_heartbeat_prevents_stale_recovery(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        9,
        20,
        quota_day_utc=QUOTA_DAY,
        reservation_id="active-call",
    )
    now = datetime(2026, 9, 25, 11, 9, tzinfo=timezone.utc)
    with dao.session() as session:
        entity = session.get(TokenQuotaReservationEntity, "active-call")
        entity.updated_at = datetime(2026, 9, 25, 11, 0)

    assert dao.heartbeat("active-call")
    assert (
        dao.recover_stale_pending(
            "tenant-a", "alice", QUOTA_DAY, stale_after_seconds=900, now=now
        )
        == 0
    )
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (0, 9)


def test_new_reservation_recovers_stale_pending_budget(dao):
    dao.reserve(
        "tenant-a",
        "alice",
        9,
        10,
        quota_day_utc=QUOTA_DAY,
        reservation_id="crashed-call",
    )
    with dao.session() as session:
        entity = session.get(TokenQuotaReservationEntity, "crashed-call")
        entity.updated_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            minutes=16
        )

    with pytest.raises(TokenQuotaExceededError):
        dao.reserve(
            "tenant-a",
            "alice",
            2,
            10,
            quota_day_utc=QUOTA_DAY,
            reservation_id="next-call",
        )

    assert dao.get_reservation("crashed-call").state == "settled"
    assert dao.get_daily_totals("tenant-a", "alice", QUOTA_DAY) == (9, 0)


def test_concurrent_reservations_cannot_exceed_daily_limit(tmp_path):
    # Use a file-backed database so every worker owns a distinct connection;
    # an in-memory single-connection test would not exercise real contention.
    db.init_db(
        f"sqlite:///{tmp_path / 'quota-race.sqlite'}",
        engine_args={"connect_args": {"timeout": 30}},
    )
    db.create_all()

    def reserve(index):
        try:
            return TokenQuotaDao().reserve(
                "tenant-a",
                "alice",
                1,
                17,
                quota_day_utc=QUOTA_DAY,
                reservation_id=f"parallel-{index}",
            )
        except TokenQuotaExceededError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(reserve, range(60)))

    successes = [result for result in results if result is not None]
    assert len(successes) == 17
    assert dao_totals("tenant-a", "alice", QUOTA_DAY) == (0, 17)


def dao_totals(tenant_id, user_id, quota_day_utc):
    return TokenQuotaDao().get_daily_totals(tenant_id, user_id, quota_day_utc)
