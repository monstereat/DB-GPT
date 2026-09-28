from types import SimpleNamespace

import pytest

from dbgpt_app.openapi.api_v1 import api_v1 as chat_api_module
from dbgpt_app.scene.chat_dashboard import chat as chat_dashboard_module
from dbgpt_app.scene.chat_dashboard.chat import ChatDashboard


def test_dashboard_chart_execution_uses_authenticated_row_policy(monkeypatch):
    calls = {}
    audit_context = {
        "actor_user_id": "analyst-a",
        "data_source_id": "sales-db",
        "role": "sales_analyst",
        "tenant_id": "tenant-a",
        "region_id": "a-gz",
        "authorization_policy_version": "dashboard-sql-policy-v1",
        "trace_id": "conversation-a",
    }

    def prepare_database_query(sql, context, connector):
        calls["policy"] = (sql, context, connector)
        return "SELECT order_id FROM orders WHERE tenant_id = 'tenant-a' LIMIT 1000", {
            **context,
            "schema_policy_version": "sales-schema-v1",
        }

    class _Loader:
        def get_chart_values_by_conn(
            self, connector, sql, *, audit_context, verified_execution_context=None
        ):
            calls["execution"] = (
                connector,
                sql,
                audit_context,
                verified_execution_context,
            )
            return ["order_id"], []

    connector = object()
    monkeypatch.setattr(
        chat_dashboard_module, "prepare_database_query", prepare_database_query
    )
    monkeypatch.setattr(chat_dashboard_module, "DashboardDataLoader", _Loader)

    chat = ChatDashboard.__new__(ChatDashboard)
    chat._chat_param = SimpleNamespace(
        user_name="analyst-a",
        user_role="sales_analyst",
        tenant_id="tenant-a",
        region_id="a-gz",
    )
    chat.db_name = "sales-db"
    chat.database = connector
    chat.chat_session_id = "conversation-a"
    chat.report_name = "report"

    result = chat.do_action(
        [
            SimpleNamespace(
                sql="SELECT order_id FROM orders WHERE status = 'paid' OR 1 = 1",
                title="Orders",
                showcase="bar",
                thoughts="Paid orders",
            )
        ]
    )

    assert calls["policy"][1] == audit_context
    assert calls["policy"][2] is connector
    assert calls["execution"][1].endswith("LIMIT 1000")
    assert calls["execution"][2]["schema_policy_version"] == "sales-schema-v1"
    assert len(result.charts) == 1


def test_dashboard_policy_failure_is_audited_without_exception_text(
    monkeypatch, caplog
):
    sql = "SELECT email FROM users WHERE email='private@example.test'"

    def reject_query(_sql, _context, _connector):
        raise ValueError("private backend detail")

    monkeypatch.setattr(chat_dashboard_module, "prepare_database_query", reject_query)

    class _UnusedLoader:
        def get_chart_values_by_conn(self, *_args, **_kwargs):
            raise AssertionError("a rejected query must not reach execution")

    monkeypatch.setattr(chat_dashboard_module, "DashboardDataLoader", _UnusedLoader)
    caplog.set_level("INFO")
    chat = ChatDashboard.__new__(ChatDashboard)
    chat._chat_param = SimpleNamespace(
        user_name="analyst-a",
        user_role="normal",
        tenant_id="tenant-a",
        region_id=None,
    )
    chat.db_name = "sales-db"
    chat.database = object()
    chat.chat_session_id = "conversation-a"
    chat.report_name = "report"

    result = chat.do_action(
        [SimpleNamespace(sql=sql, title="Users", showcase="table", thoughts="")]
    )

    assert result.charts == []
    assert '"actor_user_id": "analyst-a"' in caplog.text
    assert '"data_source_id": "sales-db"' in caplog.text
    assert '"authorization_policy_version": "dashboard-sql-policy-v1"' in caplog.text
    assert '"status": "failed"' in caplog.text
    assert '"category": "ValueError"' in caplog.text
    assert "query_sha256=" in caplog.text
    assert "private backend detail" not in caplog.text
    assert "private@example.test" not in caplog.text
    assert sql not in caplog.text


@pytest.mark.asyncio
async def test_chat_instance_copies_verified_identity_claims(monkeypatch):
    async def blocking_func_to_async(_system_app, _func, *_args, **kwargs):
        return kwargs["chat_param"]

    monkeypatch.setattr(
        chat_api_module, "blocking_func_to_async", blocking_func_to_async
    )
    dialogue = SimpleNamespace(
        chat_mode="chat_dashboard",
        conv_uid="conversation-a",
        user_name="analyst-a",
        sys_code="",
        user_input="Show sales",
        select_param="sales-db",
        model_name="model-a",
        app_code="",
        ext_info=None,
        temperature=None,
        max_new_tokens=None,
        prompt_code=None,
    )
    identity = SimpleNamespace(
        user_id="analyst-a",
        role="sales_analyst",
        tenant_id="tenant-a",
        region_id="a-gz",
    )

    chat_param = await chat_api_module.get_chat_instance(dialogue, identity)

    assert chat_param.user_role == "sales_analyst"
    assert chat_param.tenant_id == "tenant-a"
    assert chat_param.region_id == "a-gz"
