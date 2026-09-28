import json
import sqlite3

from dbgpt.datasource.sql_guard import AgentSQLBudget
from dbgpt_app.openapi.api_v1.tools.sql_query import make_sql_query


def test_main_sql_query_blocks_multiple_statements_before_connector_run():
    class _FakeConn:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):  # pragma: no cover
            raise AssertionError(f"unsafe query reached query_ex(): {sql}")

    query_tool = make_sql_query({}, _FakeConn())
    result = json.loads(query_tool(sql="SELECT 1; DELETE FROM t"))
    assert "安全限制" in result["chunks"][0]["content"]
    assert result["error"] == {
        "category": "policy_rejected",
        "retryable": False,
        "message": "安全限制: 仅允许执行一条 SQL 查询。",
    }


def test_main_sql_query_applies_datasource_sensitive_column_policy(
    tmp_path, monkeypatch
):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id"},
                "tables": [
                    {
                        "name": "products",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "internal_cost_cents",
                                "classification": "confidential",
                                "agent_queryable": False,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"ecommerce-demo": str(schema_file)}),
    )

    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):  # pragma: no cover
            raise AssertionError(f"sensitive query reached query_ex(): {sql}")

    result = json.loads(
        make_sql_query({"data_source_id": "ecommerce-demo"}, _FakeConn())(
            sql="SELECT internal_cost_cents FROM products"
        )
    )

    assert result["error"] == {
        "category": "permission_denied",
        "retryable": False,
        "message": "查询包含当前身份不可访问的敏感字段。",
    }


def test_main_sql_query_applies_server_owned_tenant_and_region_scope(
    tmp_path, monkeypatch
):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {
                    "tenant_column": "tenant_id",
                    "policy_version": "scope-v1",
                    "region_scope": {"direct": {"orders": "region_id"}},
                },
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "region_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                            {
                                "name": "order_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"sales-db": str(schema_file)}),
    )

    class _SQLiteConn:
        dialect = "sqlite"

        def __init__(self):
            self.connection = sqlite3.connect(":memory:")
            self.connection.executescript(
                "CREATE TABLE orders (tenant_id TEXT, "
                "region_id TEXT, order_id INTEGER);"
                "INSERT INTO orders VALUES "
                "('tenant-a', 'north', 1), ('tenant-a', 'south', 2), "
                "('tenant-b', 'north', 3);"
            )

        def query_ex(self, sql, timeout=None):
            cursor = self.connection.execute(sql)
            return [column[0] for column in cursor.description], cursor.fetchall()

    connector = _SQLiteConn()
    state = {
        "data_source_id": "sales-db",
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "north",
    }
    result = json.loads(
        make_sql_query(state, connector)(sql="SELECT order_id FROM orders")
    )

    assert result["chunks"][0]["content"] == "| order_id |\n| --- |\n| 1 |"

    missing_scope = json.loads(
        make_sql_query({"data_source_id": "sales-db"}, connector)(
            sql="SELECT order_id FROM orders"
        )
    )
    assert missing_scope["error"]["category"] == "permission_denied"
    connector.connection.close()


def test_main_sql_query_fails_closed_when_tenant_schema_is_unmapped(monkeypatch):
    monkeypatch.delenv("DBGPT_DATABASE_SCHEMA_FILES", raising=False)

    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):  # pragma: no cover
            raise AssertionError(f"unscoped query reached query_ex(): {sql}")

    result = json.loads(
        make_sql_query(
            {"data_source_id": "sales-db", "tenant_id": "tenant-a"}, _FakeConn()
        )(sql="SELECT 1")
    )

    assert result["error"]["category"] == "permission_denied"


def test_main_sql_query_executes_select():
    class _FakeConn:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):
            assert sql == "SELECT 1 LIMIT 1000"
            assert timeout == 30
            return ["value"], [(1,)]

    query_tool = make_sql_query({}, _FakeConn())
    result = json.loads(query_tool(sql="SELECT 1"))
    assert result["chunks"][0]["content"] == "| value |\n| --- |\n| 1 |"
    assert result["result"] == {
        "type": "sql_result",
        "columns": ["value"],
        "rows": [[1]],
        "row_count": 1,
        "truncated": False,
    }
    assert "SELECT 1" not in json.dumps(result["result"])


def test_main_sql_query_bounds_structured_rows_and_marks_truncation():
    class _FakeConn:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):
            return ["value"], [(row,) for row in range(60)]

    result = json.loads(make_sql_query({}, _FakeConn())(sql="SELECT value"))

    assert len(result["result"]["rows"]) == 50
    assert result["result"]["row_count"] == 60
    assert result["result"]["truncated"] is True


def test_main_sql_query_returns_retryable_syntax_category():
    class _FakeConn:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):  # pragma: no cover
            raise AssertionError("invalid SQL must be rejected before execution")

    result = json.loads(make_sql_query({}, _FakeConn())(sql="SELECT FROM"))

    assert result["error"]["category"] == "syntax_error"
    assert result["error"]["retryable"] is True
    assert "result" not in result


def test_main_sql_query_never_returns_raw_driver_errors():
    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            raise RuntimeError("private_schema_detail leaked by driver")

    result = json.loads(make_sql_query({}, _FakeConn())(sql="SELECT 1"))

    assert result["error"] == {
        "category": "execution_error",
        "retryable": False,
        "message": "查询执行失败。未自动重试，请检查数据源状态。",
    }
    assert "private_schema_detail" not in json.dumps(result)
    assert "result" not in result


def test_main_sql_query_enforces_single_correction_budget_per_failure_chain():
    state = {}

    class _FakeConn:
        dialect = "sqlite"
        fail = True

        def query_ex(self, sql, timeout=None):
            if self.fail:
                raise sqlite3.OperationalError("no such column: missing")
            return ["value"], [(1,)]

    connector = _FakeConn()
    query_tool = make_sql_query(state, connector)

    first = json.loads(query_tool(sql="SELECT missing FROM t"))["error"]
    second = json.loads(query_tool(sql="SELECT missing FROM t"))["error"]
    assert first["retryable"] is True
    assert first["retries_remaining"] == 0
    assert second["retryable"] is False
    assert second["retries_remaining"] == 0

    connector.fail = False
    assert "| 1 |" in json.loads(query_tool(sql="SELECT 1"))["chunks"][0]["content"]
    connector.fail = True
    assert (
        json.loads(query_tool(sql="SELECT missing FROM t"))["error"]["retryable"]
        is True
    )


def test_main_sql_query_permission_rejection_does_not_consume_budget():
    state = {}

    class _FakeConn:
        dialect = "sqlite"

    result = json.loads(make_sql_query(state, _FakeConn())(sql="DELETE FROM t"))

    assert result["error"]["category"] == "permission_denied"
    assert result["error"]["retryable"] is False
    assert "_sql_correction_budget_remaining" not in state


def test_main_sql_query_fails_closed_when_agent_budget_is_exhausted():
    state = {
        "sql_execution_budget": AgentSQLBudget(max_queries=1, max_runtime_seconds=5)
    }

    class _FakeConn:
        dialect = "sqlite"
        calls = 0

        def query_ex(self, sql, timeout=None):
            self.calls += 1
            return ["value"], [(1,)]

    connector = _FakeConn()
    query_tool = make_sql_query(state, connector)
    first = json.loads(query_tool(sql="SELECT 1"))
    second = json.loads(query_tool(sql="SELECT 2"))

    assert first["chunks"][0]["content"].endswith("| 1 |")
    assert second["error"]["category"] == "budget_exhausted"
    assert second["error"]["retryable"] is False
    assert connector.calls == 1


def test_main_sql_query_audit_has_identity_trace_and_hash_without_sql(
    caplog, tmp_path, monkeypatch
):
    caplog.set_level("INFO")
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id", "policy_version": "v1"},
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES", json.dumps({"sales-db": str(schema_file)})
    )
    state = {
        "actor_user_id": "analyst-a",
        "tenant_id": "tenant-a",
        "region_id": "south-1",
        "data_source_id": "sales-db",
        "authorization_policy_version": "datasource-visibility-v1",
        "trace_id": "conversation-a",
    }

    class _FakeConn:
        dialect = "postgresql"

        def query_ex(self, sql, timeout=None):
            assert sql == "SELECT secret_value LIMIT 1000"
            return ["value"], [(1,)]

    sql = "SELECT secret_value"
    query_tool = make_sql_query(state, _FakeConn())
    query_tool(sql=sql)

    assert '"actor_user_id": "analyst-a"' in caplog.text
    assert '"tenant_id": "tenant-a"' in caplog.text
    assert '"region_id": "south-1"' in caplog.text
    assert '"data_source_id": "sales-db"' in caplog.text
    assert '"trace_id": "conversation-a"' in caplog.text
    assert '"status": "succeeded"' in caplog.text
    assert '"returned_rows": 1' in caplog.text
    assert sql not in caplog.text
