import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dbgpt.datasource.sql_guard import sql_fingerprint
from dbgpt.util.tracer import root_tracer
from dbgpt_app.openapi.api_v1.editor import api_editor_v1
from dbgpt_app.openapi.api_v1.editor import service as editor_service_module
from dbgpt_app.openapi.api_v1.editor.api_editor_v1 import (
    chart_run,
    editor_sql_run,
    get_authorized_editor_connector,
    get_editor_chart_info,
    resolve_editor_db_name,
)
from dbgpt_app.openapi.api_v1.editor.service import EditorService, nonempty_db_name
from dbgpt_serve.utils.auth import UserRequest


def test_nonempty_db_name_skips_whitespace_before_fallback():
    assert nonempty_db_name("   ", "Walmart_Sales") == "Walmart_Sales"
    assert nonempty_db_name(None, "  orders  ") == "orders"
    assert nonempty_db_name("   ", None, "") == ""


def test_resolve_editor_db_name_from_request():
    assert resolve_editor_db_name({"db_name": " sales "}) == "sales"


def test_resolve_editor_db_name_skips_blank():
    assert resolve_editor_db_name({"db_name": "  "}) is None
    assert resolve_editor_db_name({}) is None


def test_resolve_editor_db_name_from_conversation():
    class _Conv:
        param_value = "walmart"
        messages = []

    class _Service:
        def get_storage_conv(self, conv_uid: str):
            assert conv_uid == "c1"
            return _Conv()

    assert (
        resolve_editor_db_name({"con_uid": "c1"}, editor_service=_Service())
        == "walmart"
    )


def test_resolve_editor_db_name_from_message_kwargs():
    class _Msg:
        additional_kwargs = {"param_value": "orders"}

    class _Conv:
        param_value = ""
        messages = [_Msg()]

    class _Service:
        def get_storage_conv(self, conv_uid: str):
            return _Conv()

    assert (
        resolve_editor_db_name({"conv_uid": "c2"}, editor_service=_Service())
        == "orders"
    )


class _NoDbService:
    def get_storage_conv(self, conv_uid: str):
        raise RuntimeError("should not load conversation without conv uid")


def test_editor_connector_requires_datasource_visibility(monkeypatch):
    class _Manager:
        def get_db_list(self, *, db_name, user_id):
            assert (db_name, user_id) == ("secret-db", "analyst-1")
            return []

    monkeypatch.setattr(
        api_editor_v1.ConnectorManager,
        "get_instance",
        lambda *_args: _Manager(),
    )
    monkeypatch.setattr(api_editor_v1, "CFG", SimpleNamespace(SYSTEM_APP=object()))

    with pytest.raises(HTTPException) as error:
        get_authorized_editor_connector(
            "secret-db", UserRequest(user_id="analyst-1", role="normal")
        )

    assert error.value.status_code == 403


def test_editor_conversation_access_requires_matching_owner():
    class _Service:
        def get_storage_conv(self, conv_uid):
            assert conv_uid == "conv-1"
            return SimpleNamespace(user_name="analyst-1")

    conversation = api_editor_v1.authorize_editor_conversation(
        "conv-1",
        UserRequest(user_id="analyst-1", role="normal"),
        _Service(),
    )
    assert conversation.user_name == "analyst-1"

    with pytest.raises(HTTPException) as error:
        api_editor_v1.authorize_editor_conversation(
            "conv-1",
            UserRequest(user_id="analyst-2", role="normal"),
            _Service(),
        )
    assert error.value.status_code == 404


def test_editor_conversation_admin_can_access_another_owner():
    class _Service:
        def get_storage_conv(self, conv_uid):
            return SimpleNamespace(user_name="analyst-1")

    conversation = api_editor_v1.authorize_editor_conversation(
        "conv-1", UserRequest(user_id="admin-1", role="admin"), _Service()
    )
    assert conversation.user_name == "analyst-1"


def _configure_editor_scope_policy(monkeypatch, tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
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
                            {
                                "name": "status",
                                "classification": "business",
                                "agent_queryable": True,
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
        "DBGPT_DATABASE_SCHEMA_FILES", json.dumps({"sales-db": str(schema_path)})
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler,run_param",
    [
        (
            editor_sql_run,
            {
                "db_name": "sales-db",
                "sql": "SELECT order_id FROM orders WHERE status = 'paid' OR 1 = 1",
            },
        ),
        (
            chart_run,
            {
                "db_name": "sales-db",
                "sql": "SELECT order_id FROM orders WHERE status = 'paid' OR 1 = 1",
                "chart_type": "bar",
            },
        ),
    ],
)
async def test_editor_read_queries_apply_authenticated_tenant_and_region_scope(
    handler, run_param, monkeypatch, tmp_path
):
    _configure_editor_scope_policy(monkeypatch, tmp_path)

    class _Connector:
        dialect = "sqlite"
        db_type = "sqlite"

        def query_ex(self, sql, *, params, timeout, verified_execution_context=None):
            assert "tenant_id" in sql
            assert "region_id" in sql
            assert {"tenant-a", "south", "paid"}.issubset(set(params.values()))
            assert timeout == 30
            self.executed_sql = sql
            return ["order_id"], [("order-1",)]

    connector = _Connector()
    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    result = await handler(
        run_param,
        editor_service=_NoDbService(),
        user_info=UserRequest(
            user_id="sales-1",
            role="sales",
            tenant_id="tenant-a",
            region_id="south",
        ),
    )

    assert result.success is True
    assert "tenant_id" in connector.executed_sql
    assert "region_id" in connector.executed_sql


@pytest.mark.asyncio
async def test_editor_read_query_fails_closed_without_sales_region(
    monkeypatch, tmp_path
):
    _configure_editor_scope_policy(monkeypatch, tmp_path)

    class _Connector:
        dialect = "sqlite"
        db_type = "sqlite"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("unscoped SQL reached the connector")

    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: _Connector(),
    )
    result = await editor_sql_run(
        {"db_name": "sales-db", "sql": "SELECT order_id FROM orders"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="sales-1", role="sales", tenant_id="tenant-a"),
    )

    assert result.success is False


@pytest.mark.asyncio
async def test_editor_read_query_rejects_confidential_column_before_execution(
    monkeypatch, tmp_path
):
    _configure_editor_scope_policy(monkeypatch, tmp_path)

    class _Connector:
        dialect = "sqlite"
        db_type = "sqlite"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("confidential SQL reached the connector")

    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: _Connector(),
    )
    result = await editor_sql_run(
        {
            "db_name": "sales-db",
            "sql": "SELECT internal_cost_cents FROM orders",
        },
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal", tenant_id="tenant-a"),
    )

    assert result.success is False


@pytest.mark.asyncio
async def test_chart_run_missing_db_name_returns_failed_result():
    result = await chart_run(
        {"sql": "select 1", "chart_type": "bar"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )
    assert result.success is False
    assert "db_name" in (result.err_msg or "")


@pytest.mark.asyncio
async def test_chart_run_rejects_multiple_statements_before_query(monkeypatch):
    class _Connector:
        dialect = "postgresql"
        db_type = "postgresql"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("unsafe SQL reached the connector")

    connector = _Connector()
    monkeypatch.setattr(
        "dbgpt_app.openapi.api_v1.editor.api_editor_v1.get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    result = await chart_run(
        {"db_name": "demo", "sql": "SELECT 1; DELETE FROM orders", "chart_type": "bar"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )

    assert result.success is False
    assert "安全限制" in (result.err_msg or "")


@pytest.mark.asyncio
async def test_editor_sql_run_missing_db_name_returns_failed_result():
    result = await editor_sql_run(
        {"sql": "select 1"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )
    assert result.success is False
    assert "db_name" in (result.err_msg or "")


@pytest.mark.asyncio
async def test_editor_sql_run_rejects_write_for_non_admin(monkeypatch, caplog):
    caplog.set_level("INFO")

    class _Connector:
        db_type = "postgresql"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("write SQL reached the connector")

    connector = _Connector()
    monkeypatch.setattr(
        "dbgpt_app.openapi.api_v1.editor.api_editor_v1.get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    result = await editor_sql_run(
        {"db_name": "demo", "sql": "UPDATE orders SET status = 'paid'"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )

    assert result.success is False
    assert "只读查询" in (result.err_msg or "")
    assert '"actor_user_id": "analyst-1"' in caplog.text
    assert '"status": "rejected"' in caplog.text
    assert "UPDATE orders" not in caplog.text


@pytest.mark.asyncio
async def test_editor_sql_run_rejects_admin_write_without_scoped_write_policy(
    monkeypatch, caplog
):
    caplog.set_level("INFO")

    class _Connector:
        db_type = "postgresql"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("unscoped write SQL reached the connector")

    connector = _Connector()
    monkeypatch.setattr(
        "dbgpt_app.openapi.api_v1.editor.api_editor_v1.get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    result = await editor_sql_run(
        {"db_name": "demo", "sql": "UPDATE orders SET status = 'paid'"},
        editor_service=_NoDbService(),
        user_info=UserRequest(
            user_id="admin-1", role="admin", tenant_id="tenant-a", region_id="a-gz"
        ),
    )

    assert result.success is False
    assert "只读查询" in (result.err_msg or "")
    assert '"actor_user_id": "admin-1"' in caplog.text
    assert '"role": "admin"' in caplog.text
    assert '"tenant_id": "tenant-a"' in caplog.text
    assert '"region_id": "a-gz"' in caplog.text
    assert '"data_source_id": "demo"' in caplog.text
    assert '"dialect": "postgresql"' in caplog.text
    assert '"status": "rejected"' in caplog.text
    assert '"trace_id": ' in caplog.text
    assert "UPDATE orders" not in caplog.text


@pytest.mark.asyncio
async def test_editor_sql_run_rejects_legacy_admin_write(monkeypatch):
    class _Connector:
        db_type = "postgresql"

        def query_ex(self, *args, **kwargs):  # pragma: no cover - must be rejected
            raise AssertionError("unverified write SQL reached the connector")

    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: _Connector(),
    )
    monkeypatch.setattr(
        api_editor_v1, "trusted_agent_execution_context", lambda _user_info: None
    )
    result = await editor_sql_run(
        {"db_name": "demo", "sql": "UPDATE orders SET status = 'paid'"},
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="legacy-admin", role="admin"),
    )

    assert result.success is False
    assert "只读查询" in (result.err_msg or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [editor_sql_run, chart_run])
async def test_editor_query_failure_does_not_return_driver_error(handler, monkeypatch):
    class _Connector:
        dialect = "postgresql"
        db_type = "postgresql"

        def query_ex(self, *args, **kwargs):
            raise RuntimeError("password=do-not-leak; internal schema detail")

    connector = _Connector()
    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    monkeypatch.setattr(
        api_editor_v1,
        "_apply_editor_read_policy",
        lambda sql, db_name, user_info, conn: (
            sql,
            {"authorization_policy_version": "test-policy"},
        ),
    )
    params = {"db_name": "demo", "sql": "SELECT order_id FROM orders"}
    if handler is chart_run:
        params["chart_type"] = "bar"

    result = await handler(
        params,
        editor_service=_NoDbService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )

    if handler is editor_sql_run:
        assert result.success is True
        assert result.data.result_info == "SQL execution failed."
    else:
        assert result.success is False
        assert result.err_msg == "Chart query failed."
    assert "do-not-leak" not in repr(result)
    assert "internal schema detail" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "operation_name"),
    [
        (editor_sql_run, "editor.sql_execution"),
        (chart_run, "editor.chart_query"),
    ],
)
async def test_editor_queries_create_scoped_sql_spans(
    handler, operation_name, monkeypatch
):
    class _Span:
        metadata = None

        def end(self, **kwargs):
            self.metadata = kwargs["metadata"]

    span = _Span()
    started = {}

    def start_span(operation, *, span_type, metadata):
        started["operation_name"] = operation
        started["metadata"] = metadata
        return span

    monkeypatch.setattr(root_tracer, "start_span", start_span)

    class _Connector:
        dialect = "postgresql"
        db_type = "postgresql"
        executed_sql = None

        def query_ex(self, sql, *, params, timeout, verified_execution_context=None):
            self.executed_sql = sql
            assert params == {"param_0": "south"}
            assert timeout == 30
            return ["region", "sales"], [("south", 10)]

    connector = _Connector()
    monkeypatch.setattr(
        "dbgpt_app.openapi.api_v1.editor.api_editor_v1.get_authorized_editor_connector",
        lambda db_name, user_info: connector,
    )
    monkeypatch.setattr(
        api_editor_v1,
        "_apply_editor_read_policy",
        lambda sql, db_name, user_info, _connector: (
            sql,
            {
                "actor_user_id": user_info.user_id,
                "role": user_info.role,
                "tenant_id": user_info.tenant_id,
                "region_id": user_info.region_id,
                "data_source_id": db_name,
                "authorization_policy_version": "editor-sql-policy-v1",
            },
        ),
    )
    run_param = {
        "db_name": "sales-db",
        "sql": "SELECT region, sales FROM metrics WHERE region = 'south'",
    }
    if handler is chart_run:
        run_param["chart_type"] = "bar"

    result = await handler(
        run_param,
        editor_service=_NoDbService(),
        user_info=UserRequest(
            user_id="analyst-1",
            role="sales",
            tenant_id="tenant-a",
            region_id="a-gz",
        ),
    )

    assert result.success is True
    assert started["operation_name"] == operation_name
    assert started["metadata"]["actor_user_id"] == "analyst-1"
    assert started["metadata"]["role"] == "sales"
    assert started["metadata"]["tenant_id"] == "tenant-a"
    assert started["metadata"]["region_id"] == "a-gz"
    assert started["metadata"]["data_source_id"] == "sales-db"
    assert started["metadata"]["authorization_policy_version"] == "editor-sql-policy-v1"
    assert started["metadata"]["query_sha256"] == sql_fingerprint(run_param["sql"])
    assert span.metadata["status"] == "succeeded"
    assert span.metadata["returned_rows"] == 1
    assert "south" not in repr(started) + repr(span.metadata)


@pytest.mark.asyncio
async def test_chart_replay_passes_authenticated_scope_to_service(monkeypatch, caplog):
    captured = {}
    caplog.set_level("INFO")

    class _EditorService:
        def get_storage_conv(self, conv_uid):
            return SimpleNamespace(user_name="analyst-1", param_value="sales-db")

        def get_editor_chart_info(
            self,
            conv_uid,
            chart_title,
            cfg,
            audit_context,
            verified_execution_context=None,
        ):
            captured.update(
                conv_uid=conv_uid,
                chart_title=chart_title,
                audit_context=audit_context,
                verified_execution_context=verified_execution_context,
            )
            return SimpleNamespace(success=True)

    monkeypatch.setattr(
        api_editor_v1,
        "get_authorized_editor_connector",
        lambda db_name, user_info: object(),
    )
    result = await get_editor_chart_info(
        {
            "con_uid": "conv-1",
            "chart_title": "Revenue",
            "sql": "SELECT confidential_column FROM customers",
        },
        editor_service=_EditorService(),
        user_info=UserRequest(user_id="analyst-1", role="normal"),
    )

    assert result.success is True
    assert captured["conv_uid"] == "conv-1"
    assert captured["chart_title"] == "Revenue"
    assert captured["audit_context"]["actor_user_id"] == "analyst-1"
    assert captured["audit_context"]["data_source_id"] == "sales-db"
    assert captured["audit_context"]["role"] == "normal"
    assert captured["audit_context"]["tenant_id"] is None
    assert captured["audit_context"]["conversation_id"] == "conv-1"
    assert "SELECT confidential_column" not in caplog.text


def test_editor_chart_replay_passes_scope_into_read_query(monkeypatch):
    chart_sql = "SELECT amount FROM sales"
    message = SimpleNamespace(type="view", content="chart-view", additional_kwargs={})
    service = SimpleNamespace(
        get_storage_conv=lambda _conv_uid: SimpleNamespace(
            messages=[message], param_value="sales-db"
        )
    )
    monkeypatch.setattr(
        editor_service_module,
        "_split_messages_by_round",
        lambda _messages: [[message]],
    )
    monkeypatch.setattr(
        editor_service_module,
        "_parse_pure_dict",
        lambda _content: {
            "charts": [
                {
                    "chart_name": "Revenue",
                    "chart_uid": "chart-1",
                    "chart_type": "bar",
                    "chart_desc": "Description",
                    "chart_sql": chart_sql,
                    "values": [],
                }
            ]
        },
    )
    calls = {}

    def execute_read_only_query(
        connector,
        sql,
        *,
        audit_context,
        verified_execution_context=None,
        span_name,
    ):
        calls.update(
            connector=connector,
            sql=sql,
            audit_context=audit_context,
            verified_execution_context=verified_execution_context,
            span_name=span_name,
        )
        return SimpleNamespace(columns=["amount"], rows=[(10,)])

    monkeypatch.setattr(
        editor_service_module, "execute_read_only_query", execute_read_only_query
    )
    monkeypatch.setattr(
        editor_service_module,
        "prepare_database_query",
        lambda sql, state, _connector: (sql, {**state, "tenant_id": "tenant-a"}),
    )
    connector = object()
    cfg = SimpleNamespace(
        local_db_manager=SimpleNamespace(get_connector=lambda _db_name: connector)
    )
    audit_context = {
        "actor_user_id": "analyst-1",
        "data_source_id": "sales-db",
        "trace_id": "request-trace",
    }

    result = EditorService.get_editor_chart_info(
        service, "conv-1", "Revenue", cfg, audit_context=audit_context
    )

    assert result.success is True
    assert calls == {
        "connector": connector,
        "sql": chart_sql,
        "audit_context": {**audit_context, "tenant_id": "tenant-a"},
        "verified_execution_context": None,
        "span_name": "editor.chart_replay",
    }


def test_editor_chart_replay_applies_authenticated_tenant_and_region_scope(
    monkeypatch, tmp_path
):
    _configure_editor_scope_policy(monkeypatch, tmp_path)
    chart_sql = "SELECT order_id FROM orders WHERE status = 'paid' OR 1 = 1"
    message = SimpleNamespace(type="view", content="chart-view", additional_kwargs={})
    service = SimpleNamespace(
        get_storage_conv=lambda _conv_uid: SimpleNamespace(
            messages=[message], param_value="sales-db"
        )
    )
    monkeypatch.setattr(
        editor_service_module,
        "_split_messages_by_round",
        lambda _messages: [[message]],
    )
    monkeypatch.setattr(
        editor_service_module,
        "_parse_pure_dict",
        lambda _content: {
            "charts": [
                {
                    "chart_name": "Orders",
                    "chart_uid": "chart-1",
                    "chart_type": "bar",
                    "chart_desc": "Description",
                    "chart_sql": chart_sql,
                    "values": [],
                }
            ]
        },
    )
    calls = {}

    def execute_read_only_query(
        connector,
        sql,
        *,
        audit_context,
        verified_execution_context=None,
        span_name,
    ):
        calls.update(
            sql=sql,
            audit_context=audit_context,
            verified_execution_context=verified_execution_context,
            span_name=span_name,
        )
        return SimpleNamespace(columns=["order_id"], rows=[("order-1",)])

    monkeypatch.setattr(
        editor_service_module, "execute_read_only_query", execute_read_only_query
    )

    class _Connector:
        dialect = "sqlite"

    cfg = SimpleNamespace(
        local_db_manager=SimpleNamespace(get_connector=lambda _db_name: _Connector())
    )
    result = EditorService.get_editor_chart_info(
        service,
        "conv-1",
        "Orders",
        cfg,
        audit_context={
            "actor_user_id": "sales-1",
            "data_source_id": "sales-db",
            "role": "sales",
            "tenant_id": "tenant-a",
            "region_id": "south",
        },
    )

    assert result.success is True
    assert "tenant-a" in calls["sql"]
    assert "south" in calls["sql"]
    assert calls["span_name"] == "editor.chart_replay"


@pytest.mark.asyncio
async def test_chart_editor_submit_applies_authenticated_read_policy(monkeypatch):
    view_data = {
        "charts": [
            {
                "chart_name": "Orders",
                "chart_type": "bar",
                "chart_desc": "Paid orders",
                "chart_sql": "SELECT order_id FROM orders",
                "values": [],
                "column_name": [],
            }
        ]
    }
    ai_data = [
        {
            "title": "Orders",
            "sql": "SELECT order_id FROM orders",
            "showcase": "bar",
            "thoughts": "Paid orders",
        }
    ]
    history_round = {
        "chat_order": 1,
        "messages": [
            {"type": "view", "data": {"content": json.dumps(view_data)}},
            {"type": "ai", "data": {"content": json.dumps(ai_data)}},
        ],
    }

    class _HistoryMemory:
        def get_messages(self):
            return [history_round]

        def update(self, messages):
            self.updated = messages

    class _ChatHistory:
        def get_store_instance(self, _conv_uid):
            return _HistoryMemory()

    connector = object()
    policy_calls = {}
    execution_calls = {}
    context = {
        "actor_user_id": "analyst-1",
        "data_source_id": "sales-db",
        "tenant_id": "tenant-a",
        "region_id": "a-gz",
        "role": "sales_analyst",
    }

    class _Loader:
        def get_chart_values_by_conn(
            self,
            db_conn,
            sql,
            *,
            audit_context,
            verified_execution_context=None,
            span_name,
        ):
            execution_calls.update(
                connector=db_conn,
                sql=sql,
                audit_context=audit_context,
                verified_execution_context=verified_execution_context,
                span_name=span_name,
            )
            return ["order_id"], []

    monkeypatch.setattr(api_editor_v1, "ChatHistory", _ChatHistory)
    monkeypatch.setattr(
        api_editor_v1, "authorize_editor_conversation", lambda *_args: None
    )
    monkeypatch.setattr(
        api_editor_v1, "get_authorized_editor_connector", lambda *_args: connector
    )
    monkeypatch.setattr(api_editor_v1, "DashboardDataLoader", lambda: _Loader())

    def apply_policy(sql, db_name, user_info, db_conn):
        policy_calls.update(
            sql=sql, db_name=db_name, role=user_info.role, connector=db_conn
        )
        return "SELECT order_id FROM orders WHERE tenant_id = 'tenant-a' LIMIT 1000", {
            **context,
            "authorization_policy_version": "editor-sql-policy-v1",
        }

    monkeypatch.setattr(api_editor_v1, "_apply_editor_read_policy", apply_policy)

    result = await api_editor_v1.chart_editor_submit(
        SimpleNamespace(
            conv_uid="conv-1",
            chart_title="Orders",
            db_name="sales-db",
            old_sql="SELECT order_id FROM orders",
            new_sql="SELECT order_id FROM orders WHERE status='paid' OR 1=1",
            new_chart_type="bar",
            new_comment="Paid orders",
            gmt_create=0,
        ),
        editor_service=SimpleNamespace(),
        user_info=SimpleNamespace(
            user_id="analyst-1",
            role="sales_analyst",
            tenant_id="tenant-a",
            region_id="a-gz",
        ),
    )

    assert result.success is True
    assert policy_calls["role"] == "sales_analyst"
    assert policy_calls["connector"] is connector
    assert execution_calls["sql"].endswith("LIMIT 1000")
    assert execution_calls["audit_context"]["tenant_id"] == "tenant-a"
    assert execution_calls["audit_context"]["trace_id"]
    assert execution_calls["span_name"] == "editor.chart_edit_validation"
