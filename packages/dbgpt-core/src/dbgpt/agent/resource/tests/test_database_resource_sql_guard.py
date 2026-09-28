import sqlite3

import pytest

from dbgpt.agent.resource.database import RDBMSConnectorResource
from dbgpt.datasource.sql_guard import (
    SQLQueryFailure,
    consume_sql_correction_budget,
    execute_read_only_query,
    limit_read_only_sql,
    reset_sql_correction_budget,
    sql_fingerprint,
    validate_read_only_sql,
)
from dbgpt.util.tracer import root_tracer


class _FakeConnector:
    dialect = "postgresql"

    def __init__(self):
        self.executed = []

    def query_ex(self, sql, timeout=None, verified_execution_context=None):
        self.executed.append((sql, timeout))
        return ["value"], [(1,)]


@pytest.mark.parametrize(
    "sql",
    [
        "-- comment\nDELETE FROM orders",
        "SELECT 1; DELETE FROM orders",
        "WITH changed AS (DELETE FROM orders RETURNING *) SELECT * FROM changed",
        "VALUES (1)",
        "SELECT pg_advisory_lock(123)",
        "SELECT pg_sleep(30)",
    ],
)
def test_rdbms_resource_blocks_unsafe_sql_before_connector_run(sql):
    connector = _FakeConnector()
    resource = object.__new__(RDBMSConnectorResource)
    resource._connector = connector

    with pytest.raises(ValueError, match="安全限制"):
        resource._sync_query("db", sql)

    assert connector.executed == []


def test_rdbms_resource_runs_a_valid_select():
    connector = _FakeConnector()
    resource = object.__new__(RDBMSConnectorResource)
    resource._connector = connector

    columns, rows = resource._sync_query("db", "SELECT 1")

    assert columns == ("value",)
    assert rows == [(1,)]
    assert connector.executed == [("SELECT 1 LIMIT 1000", 30)]


def test_rdbms_resource_applies_request_scoped_query_policy():
    connector = _FakeConnector()
    identity = {"actor_id": "alice", "tenant_id": "tenant-a"}
    calls = []

    def query_policy(sql, execution_context, query_connector):
        calls.append((sql, execution_context, query_connector))
        return "SELECT 2", {"actor_id": execution_context["actor_id"]}

    resource = object.__new__(RDBMSConnectorResource)
    resource._connector = connector
    resource._trusted_execution_context = identity
    resource._query_policy = query_policy

    columns, rows = resource._sync_query("db", "SELECT 1")

    assert calls == [("SELECT 1", identity, connector)]
    assert columns == ("value",)
    assert rows == [(1,)]
    assert connector.executed == [("SELECT 2 LIMIT 1000", 30)]


def test_rdbms_resource_emits_redacted_query_span(monkeypatch):
    class _Span:
        metadata = None

        def end(self, *, metadata):
            self.metadata = metadata

    span = _Span()
    started = {}

    def start_span(operation_name, *, span_type, metadata):
        started.update(
            operation_name=operation_name,
            span_type=span_type,
            metadata=metadata,
        )
        return span

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    connector = _FakeConnector()
    resource = object.__new__(RDBMSConnectorResource)
    resource._connector = connector
    sql = "SELECT private_value FROM private_table"

    resource._sync_query("private-db", sql)

    span_data = repr(started) + repr(span.metadata)
    assert started["operation_name"] == "agent.rdbms_resource_query"
    assert started["metadata"]["query_sha256"] == sql_fingerprint(sql)
    assert span.metadata["status"] == "succeeded"
    assert span.metadata["returned_rows"] == 1
    assert "private_value" not in span_data
    assert "private_table" not in span_data
    assert "private-db" not in span_data


def test_guard_fails_closed_for_unknown_database_dialect():
    class _UnknownConnector:
        dialect = "custom_engine"

    with pytest.raises(ValueError, match="暂不支持"):
        validate_read_only_sql("SELECT 1", _UnknownConnector())


def test_sql_fingerprint_does_not_include_raw_sql():
    sql = "SELECT email FROM users WHERE email='private@example.test'"

    fingerprint = sql_fingerprint(sql)

    assert len(fingerprint) == 64
    assert sql not in fingerprint
    assert "private@example.test" not in fingerprint


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1", "SELECT 1 LIMIT 1000"),
        ("SELECT 1 LIMIT 12", "SELECT 1 LIMIT 12"),
        ("SELECT 1 LIMIT 5000", "SELECT 1 LIMIT 1000"),
        (
            "WITH x AS (SELECT 1) SELECT * FROM x",
            "WITH x AS (SELECT 1) SELECT * FROM x LIMIT 1000",
        ),
    ],
)
def test_limit_read_only_sql_applies_bounded_top_level_limit(sql, expected):
    assert limit_read_only_sql(sql, _FakeConnector()) == expected


def test_execute_read_only_query_passes_timeout_and_caps_rows():
    class _LargeResultConnector(_FakeConnector):
        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            self.executed.append((sql, timeout))
            return ["value"], [(index,) for index in range(1005)]

    connector = _LargeResultConnector()
    result = execute_read_only_query(connector, "SELECT 1")

    assert connector.executed == [("SELECT 1 LIMIT 1000", 30)]
    assert len(result.rows) == 1000
    assert result.row_limit_reached is True


def test_execute_read_only_query_rejects_dialect_without_timeout():
    class _UnboundedConnector:
        dialect = "spark"

    with pytest.raises(ValueError, match="可靠查询超时"):
        execute_read_only_query(_UnboundedConnector(), "SELECT 1")


def test_syntax_error_is_retryable_but_permission_denial_is_not():
    with pytest.raises(SQLQueryFailure) as syntax:
        validate_read_only_sql("SELECT FROM", _FakeConnector())

    assert syntax.value.category == "syntax_error"
    assert syntax.value.retryable is True

    class _PermissionDeniedConnector(_FakeConnector):
        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            raise sqlite3.DatabaseError("access to private_column is prohibited")

    with pytest.raises(SQLQueryFailure) as permission:
        execute_read_only_query(_PermissionDeniedConnector(), "SELECT 1")

    assert permission.value.category == "permission_denied"
    assert permission.value.retryable is False
    assert "private_column" not in str(permission.value)


def test_sql_correction_budget_is_single_use_and_resets_after_success():
    state = {}
    syntax_failure = SQLQueryFailure("syntax_error", "bad syntax", retryable=True)

    first = consume_sql_correction_budget(state, syntax_failure)
    second = consume_sql_correction_budget(state, syntax_failure)

    assert first["retryable"] is True
    assert first["retries_remaining"] == 0
    assert second["retryable"] is False
    assert second["retries_remaining"] == 0

    reset_sql_correction_budget(state)
    assert consume_sql_correction_budget(state, syntax_failure)["retryable"] is True


def test_non_retryable_failure_does_not_consume_sql_correction_budget():
    state = {}
    permission_failure = SQLQueryFailure("permission_denied", "denied")
    syntax_failure = SQLQueryFailure("schema_error", "missing field", retryable=True)

    assert (
        consume_sql_correction_budget(state, permission_failure)["retryable"] is False
    )
    assert "_sql_correction_budget_remaining" not in state
    assert consume_sql_correction_budget(state, syntax_failure)["retryable"] is True


@pytest.mark.parametrize(
    ("driver_error", "category", "retryable"),
    [
        (
            sqlite3.OperationalError("no such column: private_field"),
            "schema_error",
            True,
        ),
        (TimeoutError("database timeout"), "timeout", False),
        (RuntimeError("private database detail"), "execution_error", False),
    ],
)
def test_driver_failures_are_classified_without_leaking_details(
    driver_error, category, retryable
):
    class _FailingConnector(_FakeConnector):
        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            raise driver_error

    with pytest.raises(SQLQueryFailure) as failure:
        execute_read_only_query(_FailingConnector(), "SELECT 1")

    assert failure.value.category == category
    assert failure.value.retryable is retryable
    assert "private_field" not in str(failure.value)
    assert "private database detail" not in str(failure.value)


@pytest.mark.parametrize(
    ("dialect", "driver_error", "category", "retryable"),
    [
        (
            "postgresql",
            type("PGSyntax", (Exception,), {"sqlstate": "42601"})(),
            "syntax_error",
            True,
        ),
        (
            "postgresql",
            type("PGSchema", (Exception,), {"pgcode": "42P01"})(),
            "schema_error",
            True,
        ),
        (
            "postgresql",
            type("PGPermission", (Exception,), {"sqlstate": "42501"})(),
            "permission_denied",
            False,
        ),
        ("mysql", Exception(1064, "syntax"), "syntax_error", True),
        ("mysql", Exception(1146, "missing table"), "schema_error", True),
        ("mysql", Exception(1142, "permission"), "permission_denied", False),
    ],
)
def test_postgresql_and_mysql_driver_codes_are_classified(
    dialect, driver_error, category, retryable
):
    class _FailingConnector:
        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            raise driver_error

    _FailingConnector.dialect = dialect
    with pytest.raises(SQLQueryFailure) as failure:
        execute_read_only_query(_FailingConnector(), "SELECT 1")

    assert failure.value.category == category
    assert failure.value.retryable is retryable
