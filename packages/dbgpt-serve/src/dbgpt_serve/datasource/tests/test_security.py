import importlib.util
import json
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from dbgpt.datasource.rdbms.base import RDBMSDatasourceParameters
from dbgpt_serve.datasource.manages.connect_config_db import (
    ConnectConfigDao,
    ConnectConfigEntity,
    DatasourceApprovalAuditEntity,
)
from dbgpt_serve.datasource.manages.connector_manager import ConnectorManager
from dbgpt_serve.datasource.security import (
    decrypt_secret,
    encrypt_secret,
    is_encrypted_secret,
    protect_persisted_state,
)


def _migration_module():
    path = Path(__file__).parents[6] / "tools" / "migrate_datasource_credentials.py"
    spec = importlib.util.spec_from_file_location("datasource_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_encryption_requires_a_persistent_key(monkeypatch):
    monkeypatch.delenv("DBGPT_DATASOURCE_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="encryption key is required"):
        encrypt_secret("password")


def test_persisted_private_fields_are_encrypted_and_round_trip(monkeypatch):
    monkeypatch.setenv("DBGPT_DATASOURCE_ENCRYPTION_KEY", "test-encryption-key")
    params = RDBMSDatasourceParameters(
        host="db.example",
        port=5432,
        user="analyst",
        database="sales",
        driver="postgresql",
        password="database-secret",
    )
    state = params.persisted_state()
    protected = protect_persisted_state(state, params)

    assert is_encrypted_secret(protected["db_pwd"])
    assert protected["db_pwd"] != "database-secret"
    assert decrypt_secret(protected["db_pwd"]) == "database-secret"
    assert protected["db_host"] == "db.example"


def test_connector_gate_runs_before_cached_connector_lookup():
    manager = ConnectorManager.__new__(ConnectorManager)

    class _Storage:
        def require_approved(self, _db_name):
            raise PermissionError("Datasource is not approved")

    manager.storage = _Storage()
    manager._connector_cache = {"sales": (0, object())}
    manager._connector_cache_lock = threading.Lock()
    with pytest.raises(PermissionError, match="not approved"):
        manager.get_connector("sales")


def test_datasource_review_is_independent_and_audited_atomically():
    engine = create_engine("sqlite://")
    ConnectConfigEntity.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            ConnectConfigEntity(
                db_type="sqlite",
                db_name="sales",
                db_path="/tmp/sales.sqlite",
                approval_status="pending",
                submitted_by="requester",
            )
        )
        session.commit()

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    dao.get_raw_session = factory
    with pytest.raises(PermissionError, match="cannot approve"):
        dao.review("sales", "requester", "approve")
    with factory() as session:
        assert session.query(DatasourceApprovalAuditEntity).count() == 0

    reviewed = dao.review("sales", "admin", "approve", "reviewed")
    assert reviewed["approval_status"] == "approved"
    assert reviewed["approved_by"] == "admin"
    assert len(dao.list_approval_audit("sales")) == 1
    with pytest.raises(ValueError, match="not pending"):
        dao.review("sales", "admin", "reject")
    engine.dispose()


def test_datasource_owner_transfer_is_atomic_audited_and_requires_reapproval():
    engine = create_engine("sqlite://")
    ConnectConfigEntity.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add(
            ConnectConfigEntity(
                db_type="sqlite",
                db_name="sales",
                db_path="/tmp/sales.sqlite",
                approval_status="approved",
                submitted_by="old-owner",
                user_id="old-owner",
                approved_by="reviewer",
                approval_reason="previous approval",
            )
        )
        session.commit()

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    dao.get_raw_session = factory
    transferred = dao.transfer_owner("sales", "admin", "new-owner", "team change")

    assert transferred["submitted_by"] == "new-owner"
    assert transferred["user_id"] == "new-owner"
    assert transferred["approval_status"] == "pending"
    assert transferred["approved_by"] is None
    assert len(dao.list_approval_audit("sales")) == 1
    audit = dao.list_approval_audit("sales")[0]
    assert audit["actor_id"] == "admin"
    assert audit["decision"] == "transfer"
    assert json.loads(audit["reason"]) == {
        "from_owner_id": "old-owner",
        "reason": "team change",
        "to_owner_id": "new-owner",
    }
    with pytest.raises(ValueError, match="already belongs"):
        dao.transfer_owner("sales", "admin", "new-owner")
    with pytest.raises(ValueError, match="not found"):
        dao.transfer_owner("missing", "admin", "new-owner")
    with factory() as session:
        assert session.query(DatasourceApprovalAuditEntity).count() == 1
    engine.dispose()


def test_legacy_migration_is_dry_run_first_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("DBGPT_DATASOURCE_ENCRYPTION_KEY", "test-encryption-key")
    db_file = tmp_path / "metadata.sqlite"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE connect_config (id INTEGER PRIMARY KEY, "
                "db_type TEXT NOT NULL, db_name TEXT NOT NULL, db_pwd TEXT, "
                "ext_config TEXT, user_id TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO connect_config "
                "(id, db_type, db_name, db_pwd, ext_config, user_id) "
                "VALUES (1, 'postgresql', 'sales', 'plain-password', "
                "'{}', 'requester')"
            )
        )
    engine.dispose()

    migrate = _migration_module().migrate
    url = f"sqlite:///{db_file}"
    assert migrate(url, apply=False) == 1
    engine = create_engine(url)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT db_pwd FROM connect_config WHERE id=1")
        ).first()
        assert row[0] == "plain-password"
        from sqlalchemy import inspect

        assert "approval_status" not in {
            item["name"] for item in inspect(connection).get_columns("connect_config")
        }
    engine.dispose()

    assert migrate(url, apply=True) == 1
    assert migrate(url, apply=True) == 0
    engine = create_engine(url)
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT db_pwd, approval_status, submitted_by "
                "FROM connect_config WHERE id=1"
            )
        ).first()
        assert is_encrypted_secret(row.db_pwd)
        assert decrypt_secret(row.db_pwd) == "plain-password"
        assert row.approval_status == "pending"
        assert row.submitted_by == "requester"
    engine.dispose()
