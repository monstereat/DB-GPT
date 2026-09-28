import sqlite3
import time

import pytest

import dbgpt.datasource.sql_guard as sql_guard
from dbgpt.datasource.sql_guard import (
    AgentSQLBudget,
    SQLQueryFailure,
    execute_read_only_query,
    sql_fingerprint,
)
from dbgpt.util.tracer import root_tracer


class _FakeConnector:
    dialect = "sqlite"

    def query_ex(self, sql, timeout=None):
        assert sql == "SELECT secret_value FROM metrics LIMIT 1000"
        assert timeout == 30
        return ["value"], [(1,)]


def test_agent_query_span_has_safe_scope_and_result_metadata(monkeypatch, caplog):
    class _Span:
        metadata = None

        def end(self, **kwargs):
            self.metadata = kwargs["metadata"]

    span = _Span()
    started = {}
    caplog.set_level("INFO")

    def start_span(operation_name, *, span_type, metadata):
        started.update(
            operation_name=operation_name,
            span_type=span_type,
            metadata=metadata,
        )
        return span

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    sql = "SELECT secret_value FROM metrics"
    context = {
        "actor_user_id": "analyst-a",
        "role": "sales",
        "tenant_id": "tenant-a",
        "region_id": "a-gz",
        "data_source_id": "sales-db",
        "authorization_policy_version": "datasource-visibility-v1",
        "trace_id": "conversation-a",
    }

    result = execute_read_only_query(_FakeConnector(), sql, audit_context=context)

    assert started["operation_name"] == "agent.sql_query"
    assert started["metadata"]["actor_user_id"] == "analyst-a"
    assert started["metadata"]["role"] == "sales"
    assert started["metadata"]["tenant_id"] == "tenant-a"
    assert started["metadata"]["region_id"] == "a-gz"
    assert started["metadata"]["conversation_trace_id"] == "conversation-a"
    assert started["metadata"]["query_sha256"] == sql_fingerprint(sql)
    assert span.metadata["status"] == "succeeded"
    assert span.metadata["query_sha256"] == result.query_sha256
    assert span.metadata["returned_rows"] == 1
    assert span.metadata["duration_ms"] >= 0
    assert sql not in repr(started) + repr(span.metadata)
    assert '"actor_user_id": "analyst-a"' in caplog.text
    assert '"tenant_id": "tenant-a"' in caplog.text
    assert '"region_id": "a-gz"' in caplog.text
    assert '"data_source_id": "sales-db"' in caplog.text
    assert '"authorization_policy_version": "datasource-visibility-v1"' in caplog.text
    assert '"status": "succeeded"' in caplog.text
    assert '"returned_rows": 1' in caplog.text
    assert '"dialect": "sqlite"' in caplog.text
    assert '"operation": "agent.sql_query"' in caplog.text
    assert sql not in caplog.text


def test_failed_agent_query_span_records_safe_category_without_driver_message(
    monkeypatch, caplog
):
    class _Span:
        metadata = None

        def end(self, **kwargs):
            self.metadata = kwargs["metadata"]

    class _FailingConnector(_FakeConnector):
        def query_ex(self, sql, timeout=None):
            raise sqlite3.DatabaseError("access to secret_column is prohibited")

    span = _Span()
    caplog.set_level("INFO")
    monkeypatch.setattr(
        root_tracer,
        "start_span",
        lambda operation_name, *, span_type, metadata: span,
    )
    sql = "SELECT secret_value FROM metrics"

    with pytest.raises(SQLQueryFailure) as failure:
        execute_read_only_query(
            _FailingConnector(),
            sql,
            audit_context={"actor_user_id": "analyst-a", "trace_id": "conv-a"},
        )

    assert failure.value.category == "permission_denied"
    assert span.metadata["status"] == "failed"
    assert span.metadata["category"] == "permission_denied"
    assert span.metadata["duration_ms"] >= 0
    assert "secret_column" not in repr(span.metadata)
    assert sql not in repr(span.metadata)
    assert '"status": "failed"' in caplog.text
    assert '"category": "permission_denied"' in caplog.text
    assert "secret_column" not in caplog.text
    assert sql not in caplog.text


def test_query_span_uses_the_requested_operation_name(monkeypatch):
    started = {}

    def start_span(operation_name, *, span_type, metadata):
        started["operation_name"] = operation_name

        class _Span:
            def end(self, **_kwargs):
                pass

        return _Span()

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    execute_read_only_query(
        _FakeConnector(),
        "SELECT secret_value FROM metrics",
        audit_context={"actor_user_id": "analyst-a"},
        span_name="dashboard.sql_query",
    )

    assert started["operation_name"] == "dashboard.sql_query"


def test_agent_sql_budget_is_shared_across_main_and_child_state_copies():
    budget = AgentSQLBudget(max_queries=1, max_runtime_seconds=5)
    main_context = {"sql_execution_budget": budget}
    child_context = {**main_context}

    class _CountingConnector:
        dialect = "sqlite"
        calls = 0

        def query_ex(self, sql, timeout=None):
            self.calls += 1
            self.timeout = timeout
            return ["value"], [(1,)]

    connector = _CountingConnector()
    execute_read_only_query(connector, "SELECT 1", audit_context=main_context)

    assert connector.timeout == 5
    with pytest.raises(SQLQueryFailure) as failure:
        execute_read_only_query(connector, "SELECT 2", audit_context=child_context)

    assert failure.value.category == "budget_exhausted"
    assert failure.value.retryable is False
    assert connector.calls == 1


def test_agent_sql_budget_accounts_runtime_and_bounds_parallel_reservations():
    budget = AgentSQLBudget(max_queries=3, max_runtime_seconds=4)
    first = budget.reserve_query(30)
    assert first == 4
    with pytest.raises(SQLQueryFailure) as parallel_failure:
        budget.reserve_query(30)
    assert parallel_failure.value.category == "budget_exhausted"

    budget.record_query(first, 2)
    second = budget.reserve_query(30)
    assert second == 2
    budget.record_query(second, 2)

    with pytest.raises(SQLQueryFailure) as elapsed_failure:
        budget.reserve_query(30)
    assert elapsed_failure.value.category == "budget_exhausted"


def test_agent_sql_budget_counts_connector_runtime_not_validation_time(monkeypatch):
    class _RecordingBudget(AgentSQLBudget):
        def record_query(self, reserved_seconds, elapsed_seconds):
            self.recorded_elapsed = elapsed_seconds
            super().record_query(reserved_seconds, elapsed_seconds)

    class _SlowConnector:
        dialect = "sqlite"

        def query_ex(self, _sql, timeout=None):
            started = time.monotonic()
            time.sleep(0.005)
            self.connector_elapsed = time.monotonic() - started
            return ["value"], [(1,)]

    original_validate = sql_guard.limit_read_only_sql

    def slow_validation(sql, connector):
        time.sleep(0.1)
        return original_validate(sql, connector)

    monkeypatch.setattr(sql_guard, "limit_read_only_sql", slow_validation)
    connector = _SlowConnector()
    budget = _RecordingBudget(max_queries=1, max_runtime_seconds=5)

    execute_read_only_query(
        connector, "SELECT 1", audit_context={"sql_execution_budget": budget}
    )

    assert budget.recorded_elapsed >= connector.connector_elapsed * 0.5
    assert budget.recorded_elapsed <= connector.connector_elapsed + 0.025


@pytest.mark.parametrize("dialect", ["postgresql", "mysql"])
def test_rdbms_queries_apply_timeout_and_result_limit(dialect):
    class _RdbmsConnector:
        def __init__(self):
            self.received_sql = None
            self.received_timeout = None

        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            self.received_sql = sql
            self.received_timeout = timeout
            self.verified_execution_context = verified_execution_context
            return ["value"], [(value,) for value in range(1100)]

    connector = _RdbmsConnector()
    connector.dialect = dialect

    result = execute_read_only_query(connector, "SELECT value FROM metrics")

    assert connector.received_sql == "SELECT value FROM metrics LIMIT 1000"
    assert connector.received_timeout == 30
    assert len(result.rows) == 1000
    assert result.row_limit_reached is True


def test_postgresql_execution_context_is_separate_from_audit_metadata():
    class _PostgreSQLConnector:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            self.context = verified_execution_context
            return ["value"], [(1,)]

    connector = _PostgreSQLConnector()
    audit_context = {"tenant_id": "forged-audit-tenant"}
    verified_context = {"source": "verified_oidc_jwt", "tenant_id": "tenant-a"}

    execute_read_only_query(
        connector,
        "SELECT value FROM metrics",
        audit_context=audit_context,
        verified_execution_context=verified_context,
    )
    assert connector.context == verified_context

    execute_read_only_query(
        connector,
        "SELECT value FROM metrics",
        audit_context=audit_context,
    )
    assert connector.context is None
