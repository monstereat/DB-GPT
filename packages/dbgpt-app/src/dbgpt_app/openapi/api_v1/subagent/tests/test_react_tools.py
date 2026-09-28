"""Unit tests for ``make_react_tools`` factory (plan stage 1, Task 1.6).

Verifies:
    1. The factory returns a dict with all 9 expected tool keys.
    2. State isolation — two calls with different ``react_state`` produce
       independent tool sets that capture their own state (writing one
       state does not affect the other; work_dir differs by conv_id).
    3. Read-only resources (db/knowledge) default to None and tools degrade
       gracefully with the existing user-facing messages.
"""

import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from dbgpt_app.openapi.api_v1.subagent.react_tools import make_react_tools
from dbgpt_app.openapi.api_v1.tools.metric_query import _month_expression

_EXPECTED_TOOLS = {
    "load_skill",
    "load_tools",
    "knowledge_retrieve",
    "metric_catalog",
    "metric_query",
    "sql_query",
    "code_interpreter",
    "shell_interpreter",
    "execute_skill_script_file",
    "html_interpreter",
}


def test_factory_returns_all_expected_tools():
    tools = make_react_tools({"conv_id": "c1"})
    assert set(tools.keys()) == _EXPECTED_TOOLS
    # @tool returns a callable wrapper; the FunctionTool is on wrapper._tool.
    for name, t in tools.items():
        assert callable(t)
        assert t._tool.name == name


def test_two_calls_return_distinct_tool_objects():
    state_a = {"conv_id": "conv_a"}
    state_b = {"conv_id": "conv_b"}
    tools_a = make_react_tools(state_a)
    tools_b = make_react_tools(state_b)
    # Distinct closures => distinct tool objects per call.
    for name in _EXPECTED_TOOLS:
        assert tools_a[name] is not tools_b[name]


def test_state_isolation_load_skill_writes_only_its_own_state():
    """load_skill writes matched/skill_prompt into the captured state.

    A miss (skill not found) must not mutate state; and each tool set must
    only ever touch the dict it captured — never the sibling agent's dict.
    """
    state_a = {"conv_id": "conv_a"}
    state_b = {"conv_id": "conv_b"}
    tools_a = make_react_tools(state_a)

    # Call A's load_skill with a non-existent skill: returns "not found",
    # and crucially does NOT leak into state_b.
    out = tools_a["load_skill"](skill_name="__no_such_skill__", file_path="x")
    parsed = json.loads(out)
    assert "not found" in parsed["chunks"][0]["content"]
    # state_b is the sibling agent — must be untouched by A's tool.
    assert "matched" not in state_b
    assert "skill_prompt" not in state_b


@pytest.mark.asyncio
async def test_code_interpreter_isolates_generated_images_per_state():
    """Each agent's code_interpreter writes artifacts only to its own state.

    The empty-code path returns before spawning a subprocess, but a real run
    appends to ``react_state['generated_images']``. We assert the two tool
    sets are independently callable and that the captured state dicts are
    distinct objects, so a write in one can never appear in the other.
    """
    state_a = {"conv_id": "conv_AAA"}
    state_b = {"conv_id": "conv_BBB"}
    tools_a = make_react_tools(state_a)
    tools_b = make_react_tools(state_b)

    out_a = await tools_a["code_interpreter"](code="")
    out_b = await tools_b["code_interpreter"](code="")
    assert "No code provided" in json.loads(out_a)["chunks"][0]["content"]
    assert "No code provided" in json.loads(out_b)["chunks"][0]["content"]

    # Simulate an artifact landing in A's state; B must stay clean.
    state_a.setdefault("generated_images", []).append("/images/a.png")
    assert state_b.get("generated_images") is None


def test_sql_query_degrades_when_no_database():
    tools = make_react_tools({"conv_id": "c1"}, database_connector=None)
    out = tools["sql_query"](sql="SELECT 1")
    parsed = json.loads(out)
    assert "未选择数据库" in parsed["chunks"][0]["content"]


def test_metric_catalog_is_scoped_to_operator_mapped_datasource(tmp_path, monkeypatch):
    catalog_file = tmp_path / "metrics.json"
    catalog_file.write_text(
        json.dumps(
            {
                "catalog_version": "1.0.0",
                "default_metric_versions": {"sales_amount": "1.0.0"},
                "metrics": [
                    {
                        "id": "sales_amount",
                        "version": "1.0.0",
                        "name": "销售额",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "统计已完成订单金额。",
                        "source_table": "orders",
                        "amount_column": "total_cents",
                    },
                    {
                        "id": "sales_amount",
                        "version": "2.0.0",
                        "name": "销售额",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "另一个显式发布版本。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_METRIC_CATALOG_FILES",
        json.dumps({"sales-db": str(catalog_file), "other-db": "missing.json"}),
    )

    tool = make_react_tools({"data_source_id": "sales-db"})["metric_catalog"]
    parsed = json.loads(tool(metric_id="sales_amount"))

    assert parsed["catalog"]["catalog_version"] == "1.0.0"
    assert len(parsed["catalog"]["metrics"]) == 1
    assert parsed["catalog"]["metrics"][0]["version"] == "1.0.0"
    assert parsed["catalog"]["metrics"][0]["default_version"] == "1.0.0"
    assert "source_table" not in parsed["catalog"]["metrics"][0]
    explicit = json.loads(tool(metric_id="sales_amount", metric_version="2.0.0"))
    assert explicit["catalog"]["metrics"][0]["version"] == "2.0.0"

    other = make_react_tools({"data_source_id": "other-db"})["metric_catalog"]
    assert "没有可用的服务端指标目录" in json.loads(other())["chunks"][0]["content"]


def test_metric_catalog_hides_metrics_outside_the_verified_role(monkeypatch):
    import dbgpt_app.openapi.api_v1.tools.metric_catalog as metric_catalog_module

    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {
            "sales_amount": "1.0.0",
            "internal_margin": "1.0.0",
        },
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "name": "Sales",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "Sales definition",
                "dependencies": [],
                "dependency_versions": {},
            },
            {
                "id": "internal_margin",
                "version": "1.0.0",
                "name": "Internal margin",
                "calculation": "sum",
                "unit": "percent",
                "definition": "Internal definition",
                "dependencies": [],
                "dependency_versions": {},
                "allowed_roles": ["admin"],
            },
        ],
    }
    monkeypatch.setattr(
        metric_catalog_module,
        "load_database_metric_catalog",
        lambda *_args: catalog,
    )

    normal_catalog = json.loads(
        make_react_tools({"data_source_id": "sales-db", "role": "normal"})[
            "metric_catalog"
        ]()
    )
    admin_catalog = json.loads(
        make_react_tools({"data_source_id": "sales-db", "role": "admin"})[
            "metric_catalog"
        ]()
    )

    assert [m["id"] for m in normal_catalog["catalog"]["metrics"]] == ["sales_amount"]
    assert [m["id"] for m in admin_catalog["catalog"]["metrics"]] == [
        "sales_amount",
        "internal_margin",
    ]
    assert "allowed_roles" not in json.dumps(normal_catalog)


def test_metric_query_rejects_role_restricted_metrics_before_execution(monkeypatch):
    import dbgpt_app.openapi.api_v1.tools.metric_query as metric_query_module

    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {"internal_margin": "1.0.0"},
        "metrics": [
            {
                "id": "internal_margin",
                "version": "1.0.0",
                "status": "published",
                "name": "Internal margin",
                "calculation": "sum",
                "unit": "percent",
                "definition": "Internal definition",
                "allowed_roles": ["admin"],
                "source_table": "orders",
                "amount_column": "total_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "completed",
                "period_table": "orders",
                "period_date_column": "created_at",
            }
        ],
    }
    monkeypatch.setattr(
        metric_query_module,
        "load_database_metric_catalog",
        lambda *_args, **_kwargs: catalog,
    )
    executed = []

    class _Connector:
        dialect = "sqlite"

    def execute_query(sql):
        executed.append(sql)
        return json.dumps(
            {
                "result": {
                    "type": "sql_result",
                    "columns": ["value"],
                    "rows": [[0.4]],
                    "row_count": 1,
                    "truncated": False,
                }
            }
        )

    arguments = {
        "metric_id": "internal_margin",
        "start_date": "2026-01-01",
        "end_date": "2026-02-01",
    }
    normal_tool = metric_query_module.make_metric_query(
        {"data_source_id": "sales-db", "role": "normal"},
        _Connector(),
        execute_query,
    )
    denied = json.loads(normal_tool(**arguments))
    assert executed == []
    assert "无效，未执行查询" in denied["chunks"][0]["content"]

    admin_tool = metric_query_module.make_metric_query(
        {"data_source_id": "sales-db", "role": "admin"},
        _Connector(),
        execute_query,
    )
    allowed = json.loads(admin_tool(**arguments))
    assert len(executed) == 1
    assert allowed["metric"]["id"] == "internal_margin"


def test_metric_catalog_emits_a_bounded_agent_span(monkeypatch):
    import dbgpt_app.openapi.api_v1.tools.metric_catalog as metric_catalog_module

    spans = []
    ended = []

    class _FakeTracer:
        def start_span(self, operation_name, **kwargs):
            span = {"operation_name": operation_name, **kwargs}
            spans.append(span)
            return span

        def end_span(self, span, **kwargs):
            ended.append((span, kwargs["metadata"]))

    monkeypatch.setattr(metric_catalog_module, "root_tracer", _FakeTracer())
    monkeypatch.setattr(
        metric_catalog_module,
        "load_database_metric_catalog",
        lambda _: {
            "catalog_version": "1.0.0",
            "default_metric_versions": {"sales_amount": "1.0.0"},
            "metrics": [
                {
                    "id": "sales_amount",
                    "version": "1.0.0",
                    "name": "Sales",
                    "calculation": "sum",
                    "unit": "CNY_cent",
                    "definition": "Completed sales amount",
                    "dependencies": [],
                    "dependency_versions": {},
                }
            ],
        },
    )

    catalog_tool = metric_catalog_module.make_metric_catalog(
        {"data_source_id": "sales-db"}
    )
    result = json.loads(catalog_tool())

    assert result["catalog"]["catalog_version"] == "1.0.0"
    assert len(spans) == len(ended) == 1
    assert spans[0]["operation_name"] == "agent.metric_catalog"
    assert spans[0]["span_type"] == metric_catalog_module.SpanType.AGENT
    assert spans[0]["metadata"] == {"data_source_id": "sales-db"}
    assert ended[0][1]["data_source_id"] == "sales-db"
    assert ended[0][1]["status"] == "succeeded"
    assert isinstance(ended[0][1]["elapsed_ms"], int)
    assert "sales_amount" not in json.dumps(ended[0][1])

    monkeypatch.setattr(
        metric_catalog_module, "load_database_metric_catalog", lambda _: None
    )
    missing_tool = metric_catalog_module.make_metric_catalog(
        {"data_source_id": "sales-db"}
    )
    assert (
        "没有可用的服务端指标目录" in json.loads(missing_tool())["chunks"][0]["content"]
    )
    assert ended[-1][1]["status"] == "catalog_missing"

    monkeypatch.setattr(
        metric_catalog_module,
        "load_database_metric_catalog",
        lambda _: {
            "catalog_version": "1.0.0",
            "default_metric_versions": {},
            "metrics": [],
        },
    )
    unpublished_tool = metric_catalog_module.make_metric_catalog(
        {"data_source_id": "sales-db"}
    )
    assert (
        "未在服务端目录中发布" in json.loads(unpublished_tool())["chunks"][0]["content"]
    )
    assert ended[-1][1]["status"] == "not_published"
    assert len(spans) == len(ended) == 3


def test_metric_query_span_parents_the_sql_execution_span(monkeypatch):
    import dbgpt.util.tracer as tracer_package
    import dbgpt_app.openapi.api_v1.tools.metric_query as metric_query_module
    from dbgpt.component import SystemApp
    from dbgpt.util.tracer import DefaultTracer, MemorySpanStorage, TracerManager
    from dbgpt_app.openapi.api_v1.tools.sql_query import make_sql_query

    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {"sales_amount": "1.0.0"},
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "status": "published",
                "calculation": "sum",
                "source_table": "orders",
                "amount_column": "total_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "completed",
                "period_table": "orders",
                "period_date_column": "created_at",
            }
        ],
    }
    monkeypatch.setattr(
        metric_query_module,
        "load_database_metric_catalog",
        lambda *_args, **_kwargs: catalog,
    )

    system_app = SystemApp()
    span_storage = MemorySpanStorage(system_app)
    system_app.register_instance(span_storage)
    tracer = DefaultTracer(system_app)
    system_app.register_instance(tracer)
    tracer_manager = TracerManager()
    tracer_manager.initialize(system_app)
    monkeypatch.setattr(metric_query_module, "root_tracer", tracer_manager)
    monkeypatch.setattr(tracer_package, "root_tracer", tracer_manager)

    class _FakeConnector:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            assert "FROM orders" in sql
            return ["value"], [(12000,)]

    state = {"data_source_id": "sales-db", "actor_user_id": "analyst-a"}
    connector = _FakeConnector()
    sql_tool = make_sql_query(state, connector)
    metric_tool = metric_query_module.make_metric_query(state, connector, sql_tool)
    request_span = tracer_manager.start_span("request")
    result = json.loads(
        metric_tool(
            metric_id="sales_amount",
            start_date="2026-01-01",
            end_date="2026-02-01",
        )
    )
    request_span.end()

    assert result["metric"] == {
        "id": "sales_amount",
        "version": "1.0.0",
        "catalog_version": "1.0.0",
    }
    ended_spans = [span for span in span_storage.spans if span.end_time is not None]
    metric_span = next(
        span for span in ended_spans if span.operation_name == "agent.metric_query"
    )
    sql_span = next(
        span for span in ended_spans if span.operation_name == "agent.sql_query"
    )
    assert metric_span.parent_span_id == request_span.span_id
    assert sql_span.parent_span_id == metric_span.span_id
    assert metric_span.metadata["status"] == "succeeded"
    assert sql_span.metadata["status"] == "succeeded"
    assert "query_sha256" not in metric_span.metadata
    assert "sql" not in json.dumps(metric_span.metadata).lower()


def test_metric_query_compiles_and_executes_pinned_metric_versions(
    tmp_path, monkeypatch, caplog
):
    caplog.set_level("INFO")
    catalog_file = tmp_path / "metrics.json"
    catalog_file.write_text(
        json.dumps(
            {
                "catalog_version": "1.0.0",
                "default_metric_versions": {
                    "sales_amount": "1.0.0",
                    "paid_refund_amount": "1.0.0",
                    "net_sales_amount": "1.0.0",
                },
                "dimensions": {
                    "region": {
                        "table": "regions",
                        "column": "name",
                        "join_column": "region_id",
                    }
                },
                "metrics": [
                    {
                        "id": "sales_amount",
                        "version": "1.0.0",
                        "name": "销售额",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "已完成订单金额",
                        "source_table": "orders",
                        "amount_column": "total_cents",
                        "date_column": "created_at",
                        "status_column": "status",
                        "status_value": "completed",
                    },
                    {
                        "id": "paid_refund_amount",
                        "version": "1.0.0",
                        "name": "退款额",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "已支付退款金额",
                        "source_table": "refunds",
                        "amount_column": "amount_cents",
                        "date_column": "created_at",
                        "status_column": "status",
                        "status_value": "paid",
                    },
                    {
                        "id": "net_sales_amount",
                        "version": "1.0.0",
                        "name": "净销售额",
                        "calculation": "subtract",
                        "unit": "CNY_cent",
                        "definition": "销售额减退款额",
                        "dependencies": ["sales_amount", "paid_refund_amount"],
                        "dependency_versions": {
                            "sales_amount": "1.0.0",
                            "paid_refund_amount": "1.0.0",
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_METRIC_CATALOG_FILES",
        json.dumps({"sales-db": str(catalog_file)}),
    )

    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE regions (tenant_id TEXT, region_id INTEGER, name TEXT);
        CREATE TABLE orders (
            tenant_id TEXT, order_id INTEGER, region_id INTEGER, created_at TEXT,
            total_cents INTEGER, status TEXT
        );
        CREATE TABLE refunds (
            tenant_id TEXT, refund_id INTEGER, order_id INTEGER, created_at TEXT,
            amount_cents INTEGER, status TEXT
        );
        INSERT INTO regions VALUES
            ('tenant-a', 1, 'Guangzhou'), ('tenant-a', 2, 'Shenzhen');
        INSERT INTO orders VALUES
            ('tenant-a', 1, 1, '2026-05-01', 10000, 'completed'),
            ('tenant-a', 2, 2, '2026-05-02', 8000, 'completed');
        INSERT INTO refunds VALUES
            ('tenant-a', 1, 1, '2026-05-03', 1000, 'paid');
        """
    )

    class _SQLiteConnector:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            cursor = connection.execute(sql)
            return [(item[0],) for item in cursor.description], cursor.fetchall()

    state = {
        "conv_id": "metric-query-test",
        "data_source_id": "sales-db",
        "actor_user_id": "analyst-a",
    }
    tool = make_react_tools(state, database_connector=_SQLiteConnector())[
        "metric_query"
    ]

    parsed = json.loads(
        tool(
            metric_id="net_sales_amount",
            start_date="2026-05-01",
            end_date="2026-06-01",
            dimension="region",
            metric_version="1.0.0",
        )
    )

    assert parsed["metric"] == {
        "id": "net_sales_amount",
        "version": "1.0.0",
        "catalog_version": "1.0.0",
    }
    assert parsed["result"]["columns"] == ["region", "net_sales_cents"]
    assert parsed["result"]["rows"] == [
        ["Guangzhou", 9000],
        ["Shenzhen", 8000],
    ]
    assert '"status": "succeeded"' in caplog.text
    assert "SELECT" not in caplog.text
    invalid = json.loads(
        tool(
            metric_id="net_sales_amount",
            start_date="2026-05-01' OR 1=1 --",
            end_date="2026-06-01",
            dimension="region",
        )
    )
    assert "未执行查询" in invalid["chunks"][0]["content"]


def test_admin_gross_margin_uses_trusted_metric_execution_only(monkeypatch):
    root = Path(__file__).resolve().parents[8]
    monkeypatch.setenv(
        "DBGPT_METRIC_CATALOG_FILES",
        json.dumps(
            {"sales-db": str(root / "examples/enterprise-text2sql/metric_catalog.json")}
        ),
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps(
            {
                "sales-db": str(
                    root / "examples/enterprise-text2sql/schema_metadata.json"
                )
            }
        ),
    )
    connection = sqlite3.connect(":memory:")
    executed = []
    connection.executescript(
        """
        CREATE TABLE orders (
            tenant_id TEXT, order_id INTEGER, region_id TEXT,
            created_at TEXT, status TEXT
        );
        CREATE TABLE order_items (
            tenant_id TEXT, order_id INTEGER, product_id TEXT,
            quantity INTEGER, unit_price_cents INTEGER
        );
        CREATE TABLE products (
            tenant_id TEXT, product_id TEXT, internal_cost_cents INTEGER
        );
        CREATE TABLE regions (
            tenant_id TEXT, region_id TEXT, name TEXT
        );
        INSERT INTO orders VALUES ('tenant-a', 1, 'a-gz', '2026-05-01', 'completed');
        INSERT INTO order_items VALUES ('tenant-a', 1, 'p1', 2, 10000);
        INSERT INTO products VALUES ('tenant-a', 'p1', 6000);
        INSERT INTO regions VALUES ('tenant-a', 'a-gz', 'Guangzhou');
        """
    )

    class _SQLiteConnector:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            executed.append(sql)
            cursor = connection.execute(sql)
            return [(item[0],) for item in cursor.description], cursor.fetchall()

    tools = make_react_tools(
        {
            "conv_id": "gross-margin-test",
            "data_source_id": "sales-db",
            "role": "admin",
            "tenant_id": "tenant-a",
        },
        database_connector=_SQLiteConnector(),
    )
    result = json.loads(
        tools["metric_query"](
            metric_id="gross_margin_rate",
            start_date="2026-04-01",
            end_date="2026-07-01",
            dimension="region",
        )
    )
    before_raw_sql = len(executed)
    normal_tools = make_react_tools(
        {
            "conv_id": "gross-margin-denied-test",
            "data_source_id": "sales-db",
            "role": "normal",
            "tenant_id": "tenant-a",
        },
        database_connector=_SQLiteConnector(),
    )
    denied = json.loads(
        normal_tools["metric_query"](
            metric_id="gross_margin_rate",
            start_date="2026-04-01",
            end_date="2026-07-01",
            dimension="region",
        )
    )
    raw_cost = json.loads(
        tools["sql_query"](sql="SELECT internal_cost_cents FROM products")
    )

    assert result["result"]["rows"] == [["Guangzhou", 40.0]]
    assert len(executed) == before_raw_sql
    assert "未执行查询" in denied["chunks"][0]["content"]
    assert raw_cost["error"]["category"] == "permission_denied"


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("sqlite", "strftime('%Y-%m', o.created_at)"),
        ("postgresql", "TO_CHAR(o.created_at, 'YYYY-MM')"),
        ("mysql", "DATE_FORMAT(o.created_at, '%Y-%m')"),
    ],
)
def test_metric_month_dimension_uses_supported_dialect_expression(dialect, expected):
    assert _month_expression(dialect, "o", "created_at") == expected


def test_sql_query_blocks_non_select():
    class _FakeConn:
        dialect = "postgresql"

        def run(self, sql):  # pragma: no cover - should never be called
            raise AssertionError("write statement must be blocked before run()")

    tools = make_react_tools({"conv_id": "c1"}, database_connector=_FakeConn())
    out = tools["sql_query"](sql="DELETE FROM t")
    parsed = json.loads(out)
    assert "安全限制" in parsed["chunks"][0]["content"]
    assert parsed["error"]["category"] == "permission_denied"
    assert parsed["error"]["retryable"] is False


def test_sql_query_classifies_driver_failure_without_leaking_details():
    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            raise RuntimeError("private backend schema detail")

    tools = make_react_tools({"conv_id": "c1"}, database_connector=_FakeConn())
    parsed = json.loads(tools["sql_query"](sql="SELECT 1"))

    assert parsed["error"] == {
        "category": "execution_error",
        "retryable": False,
        "message": "查询执行失败。未自动重试，请检查数据源状态。",
    }
    assert "private backend schema detail" not in json.dumps(parsed)


def test_sql_query_returns_bounded_structured_result_for_visualization():
    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            return [("region",), ("sales",)], [("华南", Decimal("123.45"))]

    tools = make_react_tools({"conv_id": "c-result"}, database_connector=_FakeConn())
    parsed = json.loads(tools["sql_query"](sql="SELECT region, sales FROM metrics"))

    assert parsed["result"] == {
        "type": "sql_result",
        "columns": ["region", "sales"],
        "rows": [["华南", "123.45"]],
        "row_count": 1,
        "truncated": False,
    }
    assert "| 华南 | 123.45 |" in parsed["chunks"][0]["content"]


def test_sql_query_limits_schema_corrections_per_agent_state():
    state = {"conv_id": "c-budget"}

    class _FakeConn:
        dialect = "sqlite"
        fail = True

        def query_ex(self, sql, timeout=None):
            if self.fail:
                raise sqlite3.OperationalError("no such column: missing")
            return ["value"], [(1,)]

    connector = _FakeConn()
    sql_query = make_react_tools(state, database_connector=connector)["sql_query"]
    first = json.loads(sql_query(sql="SELECT missing FROM t"))["error"]
    second = json.loads(sql_query(sql="SELECT missing FROM t"))["error"]

    assert first["retryable"] is True
    assert first["retries_remaining"] == 0
    assert second["retryable"] is False
    assert second["retries_remaining"] == 0

    connector.fail = False
    sql_query(sql="SELECT 1")
    connector.fail = True
    assert (
        json.loads(sql_query(sql="SELECT missing FROM t"))["error"]["retryable"] is True
    )


def test_subagent_sql_query_audit_inherits_actor_and_subagent_trace(
    caplog, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    import dbgpt_app.openapi.api_v1.subagent.react_tools as react_tools_module

    caplog.set_level("INFO")
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {
                    "tenant_column": "tenant_id",
                    "policy_version": "v1",
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
        "DBGPT_DATABASE_SCHEMA_FILES", json.dumps({"sales-db": str(schema_file)})
    )
    state = {
        "conv_id": "child-conv",
        "trace_id": "child-conv",
        "actor_user_id": "analyst-a",
        "role": "sales",
        "tenant_id": "tenant-a",
        "region_id": "south-1",
        "data_source_id": "sales-db",
        "authorization_policy_version": "datasource-visibility-v1",
    }
    spans = []

    class _FakeTracer:
        def start_span(self, operation_name, **kwargs):
            span = SimpleNamespace(operation_name=operation_name, **kwargs)
            spans.append({"span": span, "end": None})
            return span

        def end_span(self, span, **kwargs):
            spans[-1]["end"] = kwargs

    monkeypatch.setattr(react_tools_module, "root_tracer", _FakeTracer())

    class _FakeConn:
        dialect = "sqlite"

        def query_ex(self, sql, timeout=None):
            assert sql == (
                "SELECT order_id FROM orders WHERE orders.tenant_id = 'tenant-a' "
                "AND orders.region_id = 'south-1' LIMIT 1000"
            )
            return ["value"], [(1,)]

    sql = "SELECT order_id FROM orders"
    tools = make_react_tools(state, database_connector=_FakeConn())
    tools["sql_query"](sql=sql)

    assert '"actor_user_id": "analyst-a"' in caplog.text
    assert '"role": "sales"' in caplog.text
    assert '"tenant_id": "tenant-a"' in caplog.text
    assert '"region_id": "south-1"' in caplog.text
    assert '"data_source_id": "sales-db"' in caplog.text
    assert '"trace_id": "child-conv"' in caplog.text
    assert '"status": "succeeded"' in caplog.text
    assert '"returned_rows": 1' in caplog.text
    assert sql not in caplog.text
    assert spans[0]["span"].operation_name == "agent.sql_query"
    assert spans[0]["span"].metadata["actor_user_id"] == "analyst-a"
    assert spans[0]["end"]["metadata"]["status"] == "succeeded"
    assert spans[0]["end"]["metadata"]["returned_rows"] == 1
    assert sql not in repr(spans)
    assert "tenant-a" in repr(spans)


@pytest.mark.parametrize(
    "sql",
    [
        "-- harmless comment\nDELETE FROM t",
        "SELECT 1; DELETE FROM t",
        "WITH changed AS (DELETE FROM t RETURNING *) SELECT * FROM changed",
    ],
)
def test_sql_query_blocks_ast_write_bypasses(sql):
    class _FakeConn:
        dialect = "postgresql"

        def run(self, query):  # pragma: no cover - must be blocked before run()
            raise AssertionError(f"unsafe query reached run(): {query}")

    tools = make_react_tools({"conv_id": "c1"}, database_connector=_FakeConn())
    out = tools["sql_query"](sql=sql)
    assert "安全限制" in json.loads(out)["chunks"][0]["content"]


@pytest.mark.asyncio
async def test_knowledge_retrieve_degrades_when_no_resource():
    tools = make_react_tools({"conv_id": "c1"}, knowledge_resources=None)
    out = await tools["knowledge_retrieve"](query="q")
    parsed = json.loads(out)
    assert "No knowledge base available" in parsed["chunks"][0]["content"]


@pytest.mark.asyncio
async def test_knowledge_retrieve_emits_bounded_success_span(monkeypatch):
    from types import SimpleNamespace

    import dbgpt_app.openapi.api_v1.subagent.react_tools as react_tools_module

    spans = []

    class _FakeTracer:
        def start_span(self, operation_name, **kwargs):
            span = SimpleNamespace(operation_name=operation_name, **kwargs)
            spans.append({"span": span, "end": None})
            return span

        def end_span(self, span, **kwargs):
            spans[-1]["end"] = kwargs

    class _KnowledgeResource:
        async def retrieve(self, query):
            return [SimpleNamespace(content="private document text")]

    monkeypatch.setattr(react_tools_module, "root_tracer", _FakeTracer())
    tools = make_react_tools(
        {"conv_id": "conv-1", "data_source_id": "kb-1"},
        knowledge_resources=[_KnowledgeResource()],
    )

    out = await tools["knowledge_retrieve"](query="private search phrase")

    assert "private document text" in out
    assert spans[0]["span"].operation_name == "agent.knowledge_retrieve"
    assert spans[0]["span"].span_type == react_tools_module.SpanType.AGENT
    assert spans[0]["span"].metadata == {
        "conv_id": "conv-1",
        "data_source_id": "kb-1",
    }
    assert spans[0]["end"]["metadata"]["status"] == "succeeded"
    assert spans[0]["end"]["metadata"]["result_count"] == 1
    assert spans[0]["end"]["metadata"]["elapsed_ms"] >= 0
    assert "private search phrase" not in repr(spans)
    assert "private document text" not in repr(spans)


@pytest.mark.asyncio
async def test_knowledge_retrieve_emits_failed_span_without_query_content(monkeypatch):
    import dbgpt_app.openapi.api_v1.subagent.react_tools as react_tools_module

    ended = []

    class _FakeTracer:
        def start_span(self, operation_name, **kwargs):
            return object()

        def end_span(self, span, **kwargs):
            ended.append(kwargs["metadata"])

    class _KnowledgeResource:
        async def retrieve(self, query):
            raise RuntimeError("retrieval failed")

    monkeypatch.setattr(react_tools_module, "root_tracer", _FakeTracer())
    tools = make_react_tools(
        {"conv_id": "conv-2"}, knowledge_resources=[_KnowledgeResource()]
    )

    await tools["knowledge_retrieve"](query="private search phrase")

    assert ended[0]["status"] == "failed"
    assert "private search phrase" not in repr(ended)
    assert "retrieval failed" not in repr(ended)


@pytest.mark.asyncio
async def test_interpreter_spans_exclude_code_output_and_html_input(
    monkeypatch, tmp_path
):
    import asyncio
    from types import SimpleNamespace

    import dbgpt.configs.model_config as model_config
    import dbgpt_app.openapi.api_v1.subagent.react_tools as react_tools_module

    spans = []

    class _FakeTracer:
        def start_span(self, operation_name, **kwargs):
            span = SimpleNamespace(operation_name=operation_name, **kwargs)
            spans.append({"span": span, "end": None})
            return span

        def end_span(self, span, **kwargs):
            spans[-1]["end"] = kwargs

    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"private command output", b""

    async def _create_subprocess_exec(*args, **kwargs):
        return _FakeProcess()

    monkeypatch.setattr(react_tools_module, "root_tracer", _FakeTracer())
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _create_subprocess_exec)
    monkeypatch.setattr(model_config, "PILOT_PATH", str(tmp_path / "pilot"))
    monkeypatch.setattr(
        model_config, "STATIC_MESSAGE_IMG_PATH", str(tmp_path / "images")
    )
    tools = make_react_tools({"conv_id": "trace-test", "tenant_id": "tenant-a"})

    code = "print('private code input')"
    code_result = await tools["code_interpreter"](code=code)
    html_result = await tools["html_interpreter"](
        template_path="../../private-template.html", data={"secret": "private data"}
    )

    assert "private command output" in code_result
    assert "Invalid template_path" in html_result
    assert [item["span"].operation_name for item in spans] == [
        "agent.code_interpreter",
        "agent.html_interpreter",
    ]
    assert all(item["end"]["metadata"]["status"] == "returned" for item in spans)
    assert "private code input" not in repr(spans)
    assert "private command output" not in repr(spans)
    assert "private-template.html" not in repr(spans)
    assert "private data" not in repr(spans)
