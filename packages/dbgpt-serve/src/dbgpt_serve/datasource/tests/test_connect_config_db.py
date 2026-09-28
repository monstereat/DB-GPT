"""Datasource ownership lookup tests."""

import logging
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dbgpt_ext.datasource.rdbms.conn_postgresql import PostgreSQLParameters
from dbgpt_serve.datasource.api.schemas import (
    DatasourceCreateRequest,
    DatasourceServeResponse,
)
from dbgpt_serve.datasource.manages.connect_config_db import (
    ConnectConfigDao,
    ConnectConfigEntity,
)
from dbgpt_serve.datasource.manages.connector_manager import ConnectorManager
from dbgpt_serve.datasource.manages.db_conn_info import DBConfig
from dbgpt_serve.datasource.service.service import Service


def test_get_db_list_binds_user_and_database_values():
    class _Cursor:
        description = [("db_name",), ("user_id",)]

        def fetchall(self):
            return [("sales", "alice")]

    class _Result:
        cursor = _Cursor()

    class _Session:
        statement = None
        params = None
        closed = False

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params
            return _Result()

        def close(self):
            self.closed = True

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    session = _Session()
    dao.get_raw_session = lambda: session

    result = dao.get_db_list(
        db_name="sales' OR 1=1 --",
        user_id="alice' OR 1=1 --",
    )

    assert result == [{"db_name": "sales", "user_id": "alice"}]
    assert "sales' OR 1=1 --" not in session.statement
    assert "alice' OR 1=1 --" not in session.statement
    assert "user_id = ''" in session.statement
    assert "user_id IS NULL" in session.statement
    assert {key: value for key, value in session.params.items() if key != "db_pwd"} == {
        "user_id": "alice' OR 1=1 --",
        "db_name": "sales' OR 1=1 --",
    }
    assert session.closed


def test_add_db_does_not_log_database_credentials(caplog):
    class _Storage:
        def add_url_db(self, *args):
            assert "log-secret" in args

    class _Executor:
        def submit(self, *_args):
            pass

    class _ExecutorFactory:
        def create(self):
            return _Executor()

    class _SystemApp:
        def get_component(self, *_args):
            return _ExecutorFactory()

    manager = ConnectorManager.__new__(ConnectorManager)
    manager.storage = _Storage()
    manager.system_app = _SystemApp()
    manager._db_summary_client = type(
        "_Summary", (), {"db_summary_embedding": lambda *_args: None}
    )()

    with caplog.at_level(logging.INFO):
        manager.add_db(
            DBConfig(
                db_type="mysql",
                db_name="sales",
                db_host="db.example",
                db_port=3306,
                db_user="analyst",
                db_pwd="log-secret",
            ),
            user_id="alice",
        )

    assert "log-secret" not in caplog.text
    assert "db_name=sales" in caplog.text


def test_update_url_db_binds_all_connection_values(monkeypatch):
    monkeypatch.setenv("DBGPT_DATASOURCE_ENCRYPTION_KEY", "test-encryption-key")

    class _Session:
        statement = None
        params = None
        committed = False
        closed = False

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    session = _Session()
    dao.get_db_config = lambda _db_name: {"db_name": "sales"}
    dao.get_raw_session = lambda: session

    result = dao.update_db_info(
        db_name="sales' OR 1=1 --",
        db_type="postgresql'",
        db_host="db.example'; --",
        db_port=5432,
        db_user="analyst'",
        db_pwd="secret'",
        comment="comment'",
    )

    assert result is True
    assert "sales' OR 1=1 --" not in session.statement
    assert "secret'" not in session.statement
    assert {key: value for key, value in session.params.items() if key != "db_pwd"} == {
        "db_type": "postgresql'",
        "db_host": "db.example'; --",
        "db_port": 5432,
        "db_user": "analyst'",
        "comment": "comment'",
        "db_name": "sales' OR 1=1 --",
        "submitted_by": None,
    }
    from dbgpt_serve.datasource.security import decrypt_secret

    assert decrypt_secret(session.params["db_pwd"]) == "secret'"
    assert session.committed
    assert session.closed


def test_connect_config_write_errors_do_not_log_bound_credentials(caplog):
    class _Session:
        def execute(self, *_args):
            raise RuntimeError("driver echoed password=db-secret")

        def commit(self):
            pass

        def close(self):
            pass

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    dao.get_raw_session = lambda: _Session()

    with caplog.at_level(logging.WARNING):
        dao.add_url_db("sales", "mysql", "db.example", 3306, "analyst", "db-secret")

    assert "db-secret" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_update_file_db_binds_database_values():
    class _Session:
        statement = None
        params = None
        committed = False
        closed = False

        def execute(self, statement, params):
            self.statement = str(statement)
            self.params = params

        def commit(self):
            self.committed = True

        def close(self):
            self.closed = True

    dao = ConnectConfigDao.__new__(ConnectConfigDao)
    session = _Session()
    dao.get_db_config = lambda _db_name: {"db_name": "sales"}
    dao.get_raw_session = lambda: session

    result = dao.update_db_info(
        db_name="sales' OR 1=1 --",
        db_type="sqlite'",
        db_path="/tmp/sales'--.sqlite",
        comment="comment'",
    )

    assert result is True
    assert "sales' OR 1=1 --" not in session.statement
    assert session.params == {
        "db_type": "sqlite'",
        "db_path": "/tmp/sales'--.sqlite",
        "comment": "comment'",
        "db_name": "sales' OR 1=1 --",
        "submitted_by": None,
    }
    assert session.committed
    assert session.closed


def test_legacy_connection_test_does_not_log_or_raise_driver_details(caplog):
    class _Connector:
        @staticmethod
        def from_uri_db(**_kwargs):
            raise RuntimeError("postgresql://analyst:driver-secret@db.example/sales")

    manager = ConnectorManager.__new__(ConnectorManager)
    manager.get_cls_bydbtype = lambda _db_type: _Connector

    with pytest.raises(ValueError, match="^Test connection failed$"):
        manager.test_connect(
            DBConfig(
                db_type="postgresql",
                db_name="sales",
                db_host="db.example",
                db_user="analyst",
                db_pwd="driver-secret",
            )
        )
    assert "driver-secret" not in caplog.text


def test_connection_test_does_not_log_or_raise_driver_details(caplog):
    from dbgpt_serve.datasource.api.schemas import DatasourceCreateRequest

    manager = ConnectorManager.__new__(ConnectorManager)
    manager._create_parameters = lambda _request: object()

    def _raise_driver_error(_param):
        raise RuntimeError("postgresql://analyst:driver-secret@db.example/sales")

    manager.create_connector = _raise_driver_error
    request = DatasourceCreateRequest(
        type="postgresql",
        params={"password": "driver-secret"},
    )

    with pytest.raises(ValueError, match="^Test connection failed$"):
        manager.test_connection(request)
    assert "driver-secret" not in caplog.text


def test_datasource_response_hides_privacy_parameters():
    class _Manager:
        def _get_param_cls(self, _db_type):
            return PostgreSQLParameters

    class _Service(Service):
        @property
        def datasource_manager(self):
            return self._manager

    service = _Service.__new__(_Service)
    service._manager = _Manager()
    response = service._to_query_response(
        DatasourceServeResponse(
            id=1,
            db_type="postgresql",
            db_name="sales",
            db_host="db.example",
            db_port=5432,
            db_user="analyst",
            db_pwd="do-not-return",
            comment="demo",
        )
    )

    assert response.params["password"] == ""
    assert response.params["user"] == "analyst"


def test_datasource_update_keeps_hidden_password_when_request_omits_it(monkeypatch):
    monkeypatch.setenv("DBGPT_DATASOURCE_ENCRYPTION_KEY", "test-encryption-key")
    stored = DatasourceServeResponse(
        id=1,
        db_type="postgresql",
        db_name="sales",
        submitted_by="analyst-a",
        db_host="db.example",
        db_port=5432,
        db_user="analyst",
        db_pwd="stored-secret",
        comment="before",
    )

    class _Dao:
        updated = None

        def get_by_names(self, _db_name):
            return stored

        def update(self, _filter, values):
            self.updated = values
            return DatasourceServeResponse(
                id=1,
                db_type=values["db_type"],
                db_name=values["db_name"],
                db_host=values["db_host"],
                db_port=values["db_port"],
                db_user=values["db_user"],
                db_pwd=values["db_pwd"],
                comment=values["comment"],
            )

    class _Manager:
        def _get_param_cls(self, _db_type):
            return PostgreSQLParameters

        def _create_parameters(self, request):
            return PostgreSQLParameters.from_dict(
                request.params, ignore_extra_fields=True
            )

        def invalidate_connector(self, _db_name):
            pass

    class _Service(Service):
        @property
        def datasource_manager(self):
            return self._manager

    service = _Service.__new__(_Service)
    service._manager = _Manager()
    service._dao = _Dao()
    request = DatasourceCreateRequest(
        type="postgresql",
        params={
            "host": "db.example",
            "port": 5432,
            "user": "analyst",
            "database": "sales",
            "password": "",
        },
        description="updated",
    )

    response = service.update(request, actor_id="analyst-a")

    assert service._dao.updated["db_pwd"] != "stored-secret"
    assert service._dao.updated["submitted_by"] == "analyst-a"
    assert service._dao.updated["user_id"] == "analyst-a"
    from dbgpt_serve.datasource.security import decrypt_secret

    assert decrypt_secret(service._dao.updated["db_pwd"]) == "stored-secret"
    assert response.params["password"] == ""


def test_datasource_update_rejects_another_submitter_before_mutation(monkeypatch):
    from fastapi import HTTPException

    stored = DatasourceServeResponse(
        id=1,
        db_type="postgresql",
        db_name="sales",
        submitted_by="owner-a",
    )

    class _Dao:
        def get_by_names(self, _db_name):
            return stored

    class _Manager:
        def _get_param_cls(self, _db_type):
            return PostgreSQLParameters

    class _Service(Service):
        @property
        def datasource_manager(self):
            return self._manager

    service = _Service.__new__(_Service)
    service._dao = _Dao()
    service._manager = _Manager()

    with pytest.raises(HTTPException) as error:
        service.update(
            DatasourceCreateRequest(
                type="postgresql",
                params={"database": "sales"},
            ),
            actor_id="owner-b",
        )

    assert error.value.status_code == 404


def test_serve_datasource_list_is_filtered_to_verified_submitter():
    engine = create_engine("sqlite://")
    ConnectConfigEntity.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        session.add_all(
            [
                ConnectConfigEntity(
                    db_type="sqlite", db_name="owned", submitted_by="owner-a"
                ),
                ConnectConfigEntity(
                    db_type="sqlite", db_name="other", submitted_by="owner-b"
                ),
                ConnectConfigEntity(
                    db_type="sqlite", db_name="legacy", submitted_by=None
                ),
            ]
        )
        session.commit()

    dao = ConnectConfigDao.__new__(ConnectConfigDao)

    @contextmanager
    def session_scope():
        with factory() as session:
            yield session

    dao.session = session_scope
    dao.to_response = lambda item: DatasourceServeResponse(
        db_type=item.db_type,
        db_name=item.db_name,
        submitted_by=item.submitted_by,
    )

    try:
        rows = dao.get_list_by_owner("owner-a")
        assert [row.db_name for row in rows] == ["owned"]
    finally:
        engine.dispose()
