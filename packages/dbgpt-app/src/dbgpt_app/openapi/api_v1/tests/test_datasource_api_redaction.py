import asyncio
import json
from threading import current_thread, main_thread
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dbgpt_app.openapi.api_v1 import api_v1
from dbgpt_ext.datasource.rdbms.conn_postgresql import PostgreSQLParameters
from dbgpt_serve.datasource.api.schemas import (
    DatasourceApprovalRequest,
    DatasourceOwnerTransferRequest,
)
from dbgpt_serve.datasource.manages.db_conn_info import DBConfig
from dbgpt_serve.utils.auth import UserRequest


class _Manager:
    def _get_param_cls(self, _db_type):
        return PostgreSQLParameters


def test_database_api_redacts_password_and_privacy_fields_in_ext_config():
    source = {
        "db_type": "postgresql",
        "db_pwd": "database-secret",
        "ext_config": json.dumps({"password": "nested-secret", "schema": "analytics"}),
    }

    result = api_v1._redact_database_secrets(source, _Manager())

    assert result["db_pwd"] == ""
    assert json.loads(result["ext_config"]) == {"password": "", "schema": "analytics"}
    assert source["db_pwd"] == "database-secret"


def test_database_api_drops_malformed_ext_config_instead_of_returning_it():
    result = api_v1._redact_database_secrets(
        {
            "db_type": "postgresql",
            "db_pwd": "database-secret",
            "ext_config": "password=unparseable-secret",
        },
        _Manager(),
    )

    assert result["db_pwd"] == ""
    assert result["ext_config"] == ""


def test_chat_database_list_route_never_returns_database_password(monkeypatch):
    class _RouteManager(_Manager):
        def get_db_list(self, *, db_name, user_id):
            assert db_name is None
            assert user_id == "analyst"
            return [
                {
                    "db_name": "sales",
                    "db_type": "postgresql",
                    "db_pwd": "database-secret",
                    "ext_config": json.dumps({"password": "config-secret"}),
                }
            ]

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    result = asyncio.run(
        api_v1.db_connect_list(
            db_name=None,
            user_info=UserRequest(user_id="analyst"),
        )
    )

    assert result.data[0]["db_pwd"] == ""
    assert json.loads(result.data[0]["ext_config"]) == {"password": ""}


def test_database_resource_params_only_include_owned_and_shared_sources(monkeypatch):
    class _RouteManager:
        def get_db_list(self, *, user_id):
            assert user_id == "alice"
            rows = [
                {"db_name": "alice-db", "db_type": "postgresql", "user_id": "alice"},
                {"db_name": "bob-db", "db_type": "mysql", "user_id": "bob"},
                {"db_name": "shared-db", "db_type": "sqlite", "user_id": ""},
            ]
            return [row for row in rows if row["user_id"] in {user_id, ""}]

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    result = asyncio.run(
        api_v1.resource_params_list(
            "database", UserRequest(user_id="alice", role="normal")
        )
    )

    assert [item["param"] for item in result.data] == ["alice-db", "shared-db"]


@pytest.mark.parametrize(
    "chat_mode",
    [
        api_v1.ChatScene.ChatWithDbQA.value(),
        api_v1.ChatScene.ChatWithDbExecute.value(),
        api_v1.ChatScene.ChatDashboard.value(),
    ],
)
def test_database_chat_mode_params_filter_sources_by_user(monkeypatch, chat_mode):
    class _RouteManager:
        def get_db_list(self, *, user_id):
            assert user_id == "alice"
            return [
                {"db_name": "alice-db", "db_type": "postgresql", "user_id": "alice"},
                {"db_name": "shared-db", "db_type": "sqlite", "user_id": ""},
            ]

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    result = asyncio.run(
        api_v1.params_list(
            chat_mode=chat_mode,
            user_token=UserRequest(user_id="alice", role="normal"),
        )
    )
    assert [item["param"] for item in result.data] == ["alice-db", "shared-db"]


def test_database_resource_params_fail_closed_without_user_id(monkeypatch):
    class _RouteManager:
        def get_db_list(self, **_kwargs):
            pytest.fail("missing user ID must not request a global source list")

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    result = asyncio.run(
        api_v1.resource_params_list("database", UserRequest(role="normal"))
    )
    assert result.data == []


def test_connection_test_route_hides_driver_error_details(monkeypatch):
    class _RouteManager:
        def __init__(self):
            self.test_thread = None

        def get_db_list(self, *, db_name, user_id):
            assert db_name == "sales"
            assert user_id is None
            return []

        def test_connect(self, _db_config):
            self.test_thread = current_thread()
            raise ValueError("postgresql://analyst:driver-secret@db.example/sales")

    manager = _RouteManager()
    monkeypatch.setattr(api_v1, "CFG", SimpleNamespace(local_db_manager=manager))
    result = asyncio.run(
        api_v1.test_connect(
            DBConfig(db_type="postgresql", db_name="sales"),
            UserRequest(user_id="analyst"),
        )
    )

    assert result.success is False
    assert result.err_msg == "Database connection test failed"
    assert "driver-secret" not in str(result)
    assert manager.test_thread is not main_thread()


def test_connection_test_rejects_registered_datasource_owned_by_another_user(
    monkeypatch,
):
    class _RouteManager:
        def __init__(self):
            self.tested = False

        def get_db_list(self, *, db_name, user_id):
            assert db_name == "sales"
            if user_id is None:
                return [{"db_name": "sales", "user_id": "alice"}]
            return []

        def test_connect(self, _db_config):
            self.tested = True

    manager = _RouteManager()
    monkeypatch.setattr(api_v1, "CFG", SimpleNamespace(local_db_manager=manager))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v1.test_connect(
                DBConfig(db_type="postgresql", db_name="sales"),
                UserRequest(user_id="bob", role="normal"),
            )
        )

    assert exc_info.value.status_code == 404
    assert not manager.tested


def test_connection_test_allows_registered_datasource_owner_and_new_datasource(
    monkeypatch,
):
    class _RouteManager:
        def __init__(self):
            self.tested = []

        def get_db_list(self, *, db_name, user_id):
            if db_name == "sales" and user_id is None:
                return [{"db_name": "sales", "user_id": "alice"}]
            if db_name == "sales" and user_id == "alice":
                return [{"db_name": "sales", "user_id": "alice"}]
            return []

        def test_connect(self, db_config):
            self.tested.append(db_config.db_name)

    manager = _RouteManager()
    monkeypatch.setattr(api_v1, "CFG", SimpleNamespace(local_db_manager=manager))
    asyncio.run(
        api_v1.test_connect(
            DBConfig(db_type="postgresql", db_name="sales"),
            UserRequest(user_id="alice", role="normal"),
        )
    )
    asyncio.run(
        api_v1.test_connect(
            DBConfig(db_type="postgresql", db_name="sales"),
            UserRequest(user_id="admin-user", role="admin"),
        )
    )
    asyncio.run(
        api_v1.test_connect(
            DBConfig(db_type="postgresql", db_name="new-sales"),
            UserRequest(user_id="bob", role="normal"),
        )
    )
    assert manager.tested == ["sales", "sales", "new-sales"]


def test_db_summary_requires_owner_and_awaits_summary_embedding(monkeypatch):
    class _RouteManager:
        def __init__(self):
            self.completed = False

            class _Storage:
                def require_approved(self, db_name):
                    assert db_name == "sales"

            self.storage = _Storage()

        def get_db_list(self, *, db_name, user_id):
            if db_name == "sales" and user_id in {None, "alice"}:
                return [{"db_name": "sales", "user_id": "alice"}]
            return []

        async def async_db_summary_embedding(self, db_name, db_type):
            await asyncio.sleep(0)
            self.completed = (db_name, db_type) == ("sales", "postgresql")

    manager = _RouteManager()
    monkeypatch.setattr(api_v1, "CFG", SimpleNamespace(local_db_manager=manager))
    result = asyncio.run(
        api_v1.db_summary(
            "sales",
            "postgresql",
            UserRequest(user_id="alice", role="normal"),
        )
    )
    assert result.success is True
    assert manager.completed
    admin_result = asyncio.run(
        api_v1.db_summary(
            "sales",
            "postgresql",
            UserRequest(user_id="admin-user", role="admin"),
        )
    )
    assert admin_result.success is True


def test_db_summary_rejects_non_owner_before_embedding(monkeypatch):
    class _RouteManager:
        def get_db_list(self, *, db_name, user_id):
            return [{"db_name": "sales", "user_id": "alice"}]

        async def async_db_summary_embedding(self, *_args):
            pytest.fail("unauthorized summary must not execute")

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v1.db_summary(
                "sales",
                "postgresql",
                UserRequest(user_id="bob", role="normal"),
            )
        )
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("operation", ["edit", "delete", "refresh"])
def test_non_owner_cannot_mutate_datasource(operation, monkeypatch):
    class _RouteManager:
        def get_db_list(self, *, db_name, user_id):
            assert db_name == "sales"
            return [{"db_name": "sales", "user_id": "alice"}]

    monkeypatch.setattr(
        api_v1, "CFG", SimpleNamespace(local_db_manager=_RouteManager())
    )
    user = UserRequest(user_id="bob", role="normal")

    if operation == "edit":
        call = api_v1.db_connect_edit(
            DBConfig(db_type="postgresql", db_name="sales"), user
        )
    elif operation == "delete":
        call = api_v1.db_connect_delete(db_name="sales", user_info=user)
    else:
        call = api_v1.db_connect_refresh(
            DBConfig(db_type="postgresql", db_name="sales"), user
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(call)

    assert exc_info.value.status_code == 403


def test_datasource_review_requires_verified_admin_and_invalidates_connector(
    monkeypatch,
):
    class _Storage:
        def review(self, db_name, actor_id, decision, reason):
            assert (db_name, actor_id, decision, reason) == (
                "sales",
                "admin-1",
                "approve",
                "verified",
            )
            return {
                "db_type": "sqlite",
                "approval_status": "approved",
                "approved_by": actor_id,
                "approved_at": "2026-09-25 12:00:00",
            }

    class _RouteManager:
        storage = _Storage()
        invalidated = None
        embedded = None

        def invalidate_connector(self, db_name):
            self.invalidated = db_name

        async def async_db_summary_embedding(self, db_name, db_type):
            self.embedded = (db_name, db_type)

    manager = _RouteManager()

    async def run_in_thread(_app, func, *args):
        return func(*args)

    monkeypatch.setattr(
        api_v1,
        "CFG",
        SimpleNamespace(SYSTEM_APP=object(), local_db_manager=manager),
    )
    monkeypatch.setattr(api_v1, "blocking_func_to_async", run_in_thread)
    monkeypatch.setattr(
        api_v1,
        "trusted_agent_execution_context",
        lambda _user: {"source": "verified_oidc_jwt", "actor_id": "admin-1"},
    )
    result = asyncio.run(
        api_v1.datasource_review(
            "sales",
            DatasourceApprovalRequest(decision="approve", reason="verified"),
            UserRequest(user_id="admin-1", role="admin"),
        )
    )

    assert result.data["approval_status"] == "approved"
    assert manager.invalidated == "sales"
    assert manager.embedded == ("sales", "sqlite")


def test_datasource_review_rejects_unverified_admin(monkeypatch):
    monkeypatch.setattr(
        api_v1,
        "trusted_agent_execution_context",
        lambda _user: {"source": "development", "actor_id": "admin-1"},
    )
    with pytest.raises(HTTPException) as exc_info:
        api_v1._verified_datasource_admin(UserRequest(user_id="admin-1", role="admin"))
    assert exc_info.value.status_code == 403


def test_datasource_owner_transfer_requires_verified_admin_and_invalidates_cache(
    monkeypatch,
):
    class _Storage:
        def transfer_owner(self, db_name, actor_id, owner_id, reason):
            assert (db_name, actor_id, owner_id, reason) == (
                "sales",
                "admin-1",
                "new-owner",
                "team change",
            )
            return {"submitted_by": owner_id, "approval_status": "pending"}

    class _RouteManager:
        storage = _Storage()
        invalidated = None

        def invalidate_connector(self, db_name):
            self.invalidated = db_name

    manager = _RouteManager()

    async def run_in_thread(_app, func, *args):
        return func(*args)

    monkeypatch.setattr(
        api_v1,
        "CFG",
        SimpleNamespace(SYSTEM_APP=object(), local_db_manager=manager),
    )
    monkeypatch.setattr(api_v1, "blocking_func_to_async", run_in_thread)
    monkeypatch.setattr(
        api_v1,
        "trusted_agent_execution_context",
        lambda _user: {"source": "verified_oidc_jwt", "actor_id": "admin-1"},
    )
    result = asyncio.run(
        api_v1.datasource_owner_transfer(
            "sales",
            DatasourceOwnerTransferRequest(
                owner_id=" new-owner ", reason="team change"
            ),
            UserRequest(user_id="admin-1", role="admin"),
        )
    )

    assert result.data == {
        "db_name": "sales",
        "owner_id": "new-owner",
        "approval_status": "pending",
    }
    assert manager.invalidated == "sales"


def test_datasource_owner_transfer_rejects_unverified_admin(monkeypatch):
    monkeypatch.setattr(
        api_v1,
        "trusted_agent_execution_context",
        lambda _user: {"source": "development", "actor_id": "admin-1"},
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            api_v1.datasource_owner_transfer(
                "sales",
                DatasourceOwnerTransferRequest(owner_id="new-owner"),
                UserRequest(user_id="admin-1", role="admin"),
            )
        )
    assert exc_info.value.status_code == 403
