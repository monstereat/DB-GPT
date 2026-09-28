"""PostgreSQL query timeout transaction-scope regression tests."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from dbgpt.datasource.rdbms.base import RDBMSConnector


class _Result:
    returns_rows = True

    @staticmethod
    def fetchall():
        return [(1,)]

    @staticmethod
    def keys():
        return ["value"]


class _Session:
    def __init__(self):
        self.statements = []
        self.parameters = []
        self.statement_timeout = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append(sql)
        self.parameters.append(params)
        if "set_config('app.current_tenant'" in sql:
            return _Result()
        if sql.startswith("SET LOCAL statement_timeout = "):
            self.statement_timeout = int(sql.rsplit(" ", 1)[1])
            return None
        if sql == "SELECT cancel":
            raise OperationalError(sql, {}, Exception("statement timeout"))
        return _Result()

    def commit(self):
        self.statement_timeout = 0

    def rollback(self):
        self.statement_timeout = 0


class _PostgreSQLConnector(RDBMSConnector):
    def __init__(self):
        self._is_closed = True
        self._engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.fake_session = _Session()

    @contextmanager
    def session_scope(self, commit=True):
        try:
            yield self.fake_session
            if commit:
                self.fake_session.commit()
        except Exception:
            self.fake_session.rollback()
            raise


def test_postgresql_timeout_is_transaction_local_and_rolls_back_on_cancel():
    connector = _PostgreSQLConnector()

    with pytest.raises(TimeoutError):
        connector.query_ex("SELECT cancel", timeout=0.25)

    assert connector.fake_session.statements == [
        "SELECT set_config('app.current_tenant', :tenant_id, true)",
        "SET LOCAL statement_timeout = 250",
        "SELECT cancel",
    ]
    assert connector.fake_session.parameters[0] == {"tenant_id": ""}
    assert connector.fake_session.statement_timeout == 0


def test_postgresql_timeout_resets_after_successful_transaction():
    connector = _PostgreSQLConnector()

    assert connector.query_ex("SELECT 1", timeout=0.5) == (["value"], [(1,)])

    assert connector.fake_session.statements == [
        "SELECT set_config('app.current_tenant', :tenant_id, true)",
        "SET LOCAL statement_timeout = 500",
        "SELECT 1",
    ]
    assert connector.fake_session.statement_timeout == 0


@pytest.mark.parametrize(
    ("context", "tenant_id"),
    [
        (
            {"source": "verified_oidc_jwt", "tenant_id": "tenant-a"},
            "tenant-a",
        ),
        ({"source": "verified_oidc_jwt", "tenant_id": "tenant-b"}, "tenant-b"),
        ({"source": "legacy_dev_identity", "tenant_id": "forged"}, ""),
        (None, ""),
    ],
)
def test_postgresql_tenant_context_is_bound_and_untrusted_identity_is_cleared(
    context, tenant_id
):
    connector = _PostgreSQLConnector()

    connector.query_ex("SELECT 1", verified_execution_context=context)

    assert connector.fake_session.statements[0] == (
        "SELECT set_config('app.current_tenant', :tenant_id, true)"
    )
    assert connector.fake_session.parameters[0] == {"tenant_id": tenant_id}
    assert connector.fake_session.statements[1] == "SELECT 1"
