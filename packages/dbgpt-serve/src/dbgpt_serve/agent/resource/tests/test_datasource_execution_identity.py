import pytest

from dbgpt_serve.agent.resource import datasource


def test_datasource_resource_denies_missing_identity_before_connecting(monkeypatch):
    calls = []

    class _Manager:
        def get_connector(self, db_name):
            calls.append(db_name)
            raise AssertionError("connector must not be opened")

    monkeypatch.setattr(
        datasource, "CFG", type("Config", (), {"local_db_manager": _Manager()})()
    )

    with pytest.raises(PermissionError, match="Verified identity"):
        datasource.DatasourceResource(name="db", db_name="sales-db")

    assert calls == []


def test_datasource_resource_authorizes_before_opening_connector(monkeypatch):
    calls = []

    class _Connector:
        db_type = "sqlite"
        dialect = "sqlite"

        def get_current_db_name(self):
            return "sales-db"

    connector = _Connector()

    class _Manager:
        def get_connector(self, db_name):
            calls.append(("connect", db_name))
            return connector

    monkeypatch.setattr(
        datasource, "CFG", type("Config", (), {"local_db_manager": _Manager()})()
    )
    identity = {"source": "verified_oidc_jwt", "actor_id": "alice"}

    def access_checker(db_name, execution_context):
        calls.append(("authorize", db_name, execution_context["actor_id"]))

    resource = datasource.DatasourceResource(
        name="db",
        db_name="sales-db",
        trusted_execution_context=identity,
        access_checker=access_checker,
        query_policy=lambda sql, context, db: (sql, context),
    )

    assert calls == [("authorize", "sales-db", "alice"), ("connect", "sales-db")]
    assert resource._trusted_execution_context["data_source_id"] == "sales-db"
