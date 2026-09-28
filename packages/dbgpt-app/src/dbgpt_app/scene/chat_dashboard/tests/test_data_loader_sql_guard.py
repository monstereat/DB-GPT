import pytest

from dbgpt.datasource.sql_guard import sql_fingerprint
from dbgpt.util.tracer import root_tracer
from dbgpt_app.scene.chat_dashboard.data_loader import DashboardDataLoader


@pytest.mark.parametrize(
    "method_name",
    ["get_sql_value", "get_chart_values_by_conn"],
)
def test_dashboard_loader_rejects_write_sql_before_query(method_name):
    class _FakeConnector:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):  # pragma: no cover - must reject
            raise AssertionError(f"unsafe query reached connector: {sql}")

    loader = DashboardDataLoader()
    method = getattr(loader, method_name)
    with pytest.raises(ValueError, match="安全限制"):
        method(_FakeConnector(), "SELECT 1; DELETE FROM orders")


def test_dashboard_loader_runs_a_valid_select():
    class _FakeConnector:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            assert sql == "SELECT 1 LIMIT 1000"
            assert timeout == 30
            return ["value"], [(1,)]

    result = DashboardDataLoader().get_sql_value(_FakeConnector(), "SELECT 1")
    assert result == (["value"], [(1,)])


def test_dashboard_loader_logs_query_fingerprint_only(caplog):
    class _FakeConnector:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None, verified_execution_context=None):
            return [], []

    sql = "SELECT email FROM users WHERE email='private@example.test'"
    caplog.set_level("INFO")
    DashboardDataLoader().get_chart_values_by_conn(_FakeConnector(), sql)

    assert sql not in caplog.text
    assert "private@example.test" not in caplog.text
    assert "query_sha256=" in caplog.text


def test_dashboard_loader_passes_safe_audit_context_to_sql_span(monkeypatch, caplog):
    class _Span:
        metadata = None

        def end(self, **kwargs):
            self.metadata = kwargs["metadata"]

    span = _Span()
    started = {}

    def start_span(operation_name, *, span_type, metadata):
        started["operation_name"] = operation_name
        started["metadata"] = metadata
        return span

    monkeypatch.setattr(root_tracer, "start_span", start_span)
    caplog.set_level("INFO")

    class _FakeConnector:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            return ["value"], [(1,)]

    sql = "SELECT secret_value FROM metrics"
    DashboardDataLoader().get_sql_value(
        _FakeConnector(),
        sql,
        audit_context={
            "actor_user_id": "analyst-a",
            "role": "sales",
            "tenant_id": "tenant-a",
            "region_id": "a-gz",
            "data_source_id": "sales-db",
            "authorization_policy_version": "schema-v1",
            "trace_id": "conversation-a",
        },
    )

    assert started["operation_name"] == "dashboard.sql_query"
    assert started["metadata"]["actor_user_id"] == "analyst-a"
    assert started["metadata"]["tenant_id"] == "tenant-a"
    assert started["metadata"]["region_id"] == "a-gz"
    assert started["metadata"]["data_source_id"] == "sales-db"
    assert started["metadata"]["conversation_trace_id"] == "conversation-a"
    assert started["metadata"]["query_sha256"] == sql_fingerprint(sql)
    assert span.metadata["status"] == "succeeded"
    assert sql not in repr(started) + repr(span.metadata)
    assert '"operation": "dashboard.sql_query"' in caplog.text
    assert '"dialect": "sqlite"' in caplog.text
