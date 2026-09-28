from types import SimpleNamespace

import pytest

from dbgpt.datasource.sql_guard import (
    SQLQueryFailure,
    _execution_failure,
    consume_sql_correction_budget,
    reset_sql_correction_budget,
    validate_editor_sql,
    validate_read_only_sql,
)


class _SQLiteConnector:
    dialect = "sqlite"


class _WrappedDriverError(Exception):
    def __init__(self, original):
        self.orig = original


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT load_extension('/tmp/extension')",
        "SELECT readfile('/etc/passwd')",
        "SELECT writefile('/tmp/result', 'data')",
        "SELECT edit('value')",
        "SELECT * FROM fsdir('/tmp')",
        "SELECT * FROM pragma_table_info('orders')",
        "SELECT name FROM pragma_table_list",
        "SELECT * FROM pragma_function_list",
    ],
)
def test_sqlite_rejects_extension_file_and_pragma_access(sql):
    with pytest.raises(SQLQueryFailure, match="元数据访问") as failure:
        validate_read_only_sql(sql, _SQLiteConnector())

    assert failure.value.category == "policy_rejected"
    assert failure.value.retryable is False


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO audit SELECT readfile('/etc/passwd')",
        "UPDATE audit SET payload = writefile('/tmp/result', 'data')",
        "INSERT INTO audit SELECT name FROM pragma_table_list",
    ],
)
def test_sqlite_editor_writes_cannot_embed_file_or_metadata_functions(sql):
    with pytest.raises(SQLQueryFailure):
        validate_editor_sql(sql, _SQLiteConnector(), allow_writes=True)


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgresql", "SELECT pg_sleep(30)"),
        ("postgresql", "SELECT pg_catalog.nextval('orders_id_seq')"),
        ("postgresql", "SELECT pg_catalog.pg_read_file('/etc/passwd')"),
        ("postgresql", "SELECT pg_catalog.pg_notify('events', 'changed')"),
        (
            "postgresql",
            "SELECT pg_catalog.set_config('search_path', 'public', false)",
        ),
        ("postgresql", "SELECT * FROM orders FOR UPDATE"),
        ("postgresql", "COPY orders TO '/tmp/orders.csv'"),
        ("mysql", "SELECT SLEEP(5)"),
        ("mysql", "SELECT GET_LOCK('analytics-report', 1)"),
        ("mysql", "SELECT BENCHMARK(10000000,MD5('x'))"),
        ("mysql", "SELECT LAST_INSERT_ID(123)"),
        ("mysql", "SELECT * FROM orders INTO OUTFILE '/tmp/orders.csv'"),
    ],
)
def test_other_dialect_side_effect_function_rules_remain_active(dialect, sql):
    class _Connector:
        pass

    connector = _Connector()
    connector.dialect = dialect
    with pytest.raises(SQLQueryFailure):
        validate_read_only_sql(sql, connector)


def test_mysql_read_only_last_insert_id_remains_allowed():
    class _MySQLConnector:
        dialect = "mysql"

    assert (
        validate_read_only_sql("SELECT LAST_INSERT_ID()", _MySQLConnector())
        == "SELECT LAST_INSERT_ID()"
    )


@pytest.mark.parametrize(
    ("error", "category", "retryable", "raw_marker"),
    [
        (
            _WrappedDriverError(SimpleNamespace(sqlstate="42601")),
            "syntax_error",
            True,
            "42601",
        ),
        (
            _WrappedDriverError(SimpleNamespace(sqlstate="42P01")),
            "schema_error",
            True,
            "42P01",
        ),
        (
            _WrappedDriverError(SimpleNamespace(sqlstate="42501")),
            "permission_denied",
            False,
            "42501",
        ),
        (
            _WrappedDriverError(SimpleNamespace(pgcode="57014")),
            "timeout",
            False,
            "57014",
        ),
        (Exception(1064, "private syntax detail"), "syntax_error", True, "private"),
        (Exception(1146, "private table detail"), "schema_error", True, "private"),
        (
            Exception(1142, "private permission detail"),
            "permission_denied",
            False,
            "private",
        ),
        (TimeoutError("private query text"), "timeout", False, "private"),
        (Exception("no such table: private_table"), "schema_error", True, "private"),
        (
            Exception("access to private_column is prohibited"),
            "permission_denied",
            False,
            "private",
        ),
        (
            Exception("near private_column: syntax error"),
            "syntax_error",
            True,
            "private",
        ),
    ],
)
def test_driver_errors_are_classified_without_leaking_details(
    error, category, retryable, raw_marker
):
    failure = _execution_failure(error)

    assert failure.category == category
    assert failure.retryable is retryable
    assert raw_marker not in str(failure)


def test_correction_budget_allows_one_syntax_retry_and_never_permission_retry():
    state = {}
    syntax = SQLQueryFailure("syntax_error", "safe syntax hint", retryable=True)
    permission = SQLQueryFailure("permission_denied", "safe denial")

    first = consume_sql_correction_budget(state, syntax)
    second = consume_sql_correction_budget(state, syntax)
    denied = consume_sql_correction_budget(state, permission)

    assert first["retryable"] is True
    assert first["retries_remaining"] == 0
    assert second["retryable"] is False
    assert denied["retryable"] is False
    assert state["_sql_correction_budget_remaining"] == 0

    reset_sql_correction_budget(state)

    assert consume_sql_correction_budget(state, syntax)["retryable"] is True
