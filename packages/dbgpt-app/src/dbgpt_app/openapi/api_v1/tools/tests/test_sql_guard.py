import pytest

from dbgpt.datasource.sql_guard import validate_editor_sql
from dbgpt_app.openapi.api_v1.tools.sql_guard import (
    limit_read_only_sql,
    validate_read_only_sql,
)


class _Connector:
    dialect = "postgresql"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH summary AS (SELECT 1 AS n) SELECT n FROM summary",
        "SELECT 1 UNION SELECT 2",
        "SELECT * FROM (SELECT 1 AS n) AS nested",
    ],
)
def test_validate_accepts_single_read_only_queries(sql):
    assert validate_read_only_sql(sql, _Connector()) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "-- comment\nDELETE FROM orders",
        "WITH removed AS (DELETE FROM orders RETURNING *) SELECT * FROM removed",
        "SELECT 1; DELETE FROM orders",
        "SELECT * INTO archive FROM orders",
        "SELECT * FROM orders FOR UPDATE",
        "VALUES (1)",
        "SELECT pg_advisory_lock(123)",
        "SELECT pg_sleep(30)",
        "SELECT GET_LOCK('resource', 30)",
        "CREATE TABLE archive (id INT)",
    ],
)
def test_validate_rejects_writes_and_side_effecting_queries(sql):
    with pytest.raises(ValueError, match="安全限制"):
        validate_read_only_sql(sql, _Connector())


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgresql", "SELECT pg_catalog.nextval('orders_id_seq')"),
        ("postgresql", "SELECT pg_catalog.setval('orders_id_seq', 1)"),
        ("postgresql", "SELECT lo_from_bytea(0, '\\x01')"),
        ("postgresql", "SELECT lo_put(123, 0, '\\x01')"),
        ("postgresql", "SELECT lo_import('/tmp/secret')"),
        ("postgresql", "SELECT pg_read_file('/etc/passwd')"),
        ("postgresql", "SELECT pg_read_binary_file('/etc/shadow')"),
        ("postgresql", "SELECT pg_ls_dir('/var/lib/postgresql')"),
        ("postgresql", "SELECT pg_cancel_backend(123)"),
        ("postgresql", "SELECT pg_terminate_backend(123)"),
        ("postgresql", "SELECT pg_reload_conf()"),
        ("mysql", "SELECT LAST_INSERT_ID(123)"),
        ("mysql", "SELECT LOAD_FILE('/etc/passwd')"),
    ],
)
def test_validate_rejects_read_statements_with_database_side_effects(dialect, sql):
    connector = _Connector()
    connector.dialect = dialect
    with pytest.raises(ValueError, match="数据库/会话副作用、服务器文件访问"):
        validate_read_only_sql(sql, connector)


def test_validate_allows_read_only_mysql_last_insert_id():
    connector = _Connector()
    connector.dialect = "mysql"
    sql = "SELECT LAST_INSERT_ID()"
    assert validate_read_only_sql(sql, connector) == sql


def test_validate_rejects_unknown_dialect():
    class _UnknownConnector:
        dialect = "custom_unknown_dialect"

    with pytest.raises(ValueError, match="暂不支持"):
        validate_read_only_sql("SELECT 1", _UnknownConnector())


def test_validate_rejects_oversized_sql():
    with pytest.raises(ValueError, match="长度限制"):
        validate_read_only_sql("SELECT " + "1" * 10_000, _Connector())


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH summary AS (SELECT 1 AS n) SELECT n FROM summary",
    ],
)
def test_editor_validation_keeps_reads_read_only_and_bounded(sql):
    validated, is_write = validate_editor_sql(sql, _Connector(), allow_writes=True)
    assert validated == sql
    assert is_write is False


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders VALUES (1)",
        "UPDATE orders SET status = 'paid'",
        "DELETE FROM orders WHERE id = 1",
        "CREATE TABLE archive (id INT)",
        "ALTER TABLE orders ADD COLUMN note TEXT",
    ],
)
def test_editor_validation_allows_only_supported_table_writes(sql):
    validated, is_write = validate_editor_sql(sql, _Connector(), allow_writes=True)
    assert validated == sql
    assert is_write is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DELETE FROM orders",
        "WITH removed AS (DELETE FROM orders RETURNING *) SELECT * FROM removed",
        "CREATE USER analyst",
        "COPY orders TO '/tmp/orders.csv'",
        "UPDATE orders SET status = pg_sleep(30)",
    ],
)
def test_editor_validation_rejects_multiple_nested_and_side_effect_statements(sql):
    with pytest.raises(ValueError, match="安全限制"):
        validate_editor_sql(sql, _Connector(), allow_writes=True)


def test_editor_validation_rejects_writes_when_disabled():
    with pytest.raises(ValueError, match="安全限制"):
        validate_editor_sql("UPDATE orders SET status = 'paid'", _Connector())


@pytest.mark.parametrize(
    ("dialect", "sql", "expected"),
    [
        (
            "postgresql",
            "SELECT * FROM orders LIMIT 100",
            "SELECT * FROM orders LIMIT 100",
        ),
        (
            "postgresql",
            "SELECT * FROM orders FETCH FIRST 100 ROWS ONLY",
            "SELECT * FROM orders FETCH FIRST 100 ROWS ONLY",
        ),
        (
            "postgresql",
            "SELECT * FROM orders FETCH FIRST 5000 ROWS ONLY",
            "SELECT * FROM orders LIMIT 1000",
        ),
        (
            "postgresql",
            "SELECT * FROM orders LIMIT $1",
            "SELECT * FROM orders LIMIT 1000",
        ),
        (
            "mysql",
            "SELECT * FROM orders LIMIT 5, 5000",
            "SELECT * FROM orders LIMIT 1000 OFFSET 5",
        ),
    ],
)
def test_limit_read_only_sql_caps_results_across_dialect_limit_forms(
    dialect, sql, expected
):
    connector = _Connector()
    connector.dialect = dialect
    assert limit_read_only_sql(sql, connector) == expected
