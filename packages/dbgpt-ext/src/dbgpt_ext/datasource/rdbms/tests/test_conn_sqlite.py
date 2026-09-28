"""
Run unit test with command: pytest dbgpt/datasource/rdbms/tests/test_conn_sqlite.py
"""

import logging
import os
import tempfile

import pytest

from dbgpt.datasource.sql_guard import sql_fingerprint
from dbgpt_ext.datasource.rdbms.conn_sqlite import SQLiteConnector


@pytest.fixture
def db():
    temp_db_file = tempfile.NamedTemporaryFile(delete=False)
    temp_db_file.close()
    conn = SQLiteConnector.from_file_path(temp_db_file.name)
    yield conn
    try:
        # TODO: Failed on windows
        os.unlink(temp_db_file.name)
    except Exception as e:
        print(f"An error occurred: {e}")


def test_get_table_names(db):
    assert list(db.get_table_names()) == []


def test_get_table_info(db):
    assert db.get_table_info() == ""


def test_get_table_info_with_table(db):
    db.run("CREATE TABLE test (id INTEGER);")
    print(db._sync_tables_from_db())
    table_info = db.get_table_info()
    assert "CREATE TABLE test" in table_info


def test_run_sql(db):
    result = db.run("CREATE TABLE test(id INTEGER);")
    assert result[0] == ("id", "INTEGER", 0, None, 0)


def test_run_no_throw(db):
    assert db.run_no_throw("this is a error sql") == []


def test_run_logs_execution_audit_without_sql_text(db, caplog):
    query = "SELECT 'RUN_SENTINEL' AS value"

    with caplog.at_level(logging.INFO, logger="dbgpt.datasource.rdbms.base"):
        result = db.run(query)

    assert result == [("value",), ("RUN_SENTINEL",)]
    assert "rdbms_sql_audit" in caplog.text
    assert "operation=run" in caplog.text
    assert "status=succeeded" in caplog.text
    assert "returned_rows=1" in caplog.text
    assert sql_fingerprint(query) in caplog.text
    assert query not in caplog.text
    assert "RUN_SENTINEL" not in caplog.text


def test_run_failure_logs_safe_audit_status(db, caplog):
    query = "SELECT RUN_ERROR_SENTINEL FROM missing_table"

    with caplog.at_level(logging.INFO, logger="dbgpt.datasource.rdbms.base"):
        with pytest.raises(Exception):
            db.run(query)

    assert "operation=run" in caplog.text
    assert "status=failed" in caplog.text
    assert sql_fingerprint(query) in caplog.text
    assert "RUN_ERROR_SENTINEL" not in caplog.text


def test_get_indexes(db):
    db.run("CREATE TABLE test (name TEXT);")
    db.run("CREATE INDEX idx_name ON test(name);")
    indexes = db.get_indexes("test")
    assert indexes == [{"name": "idx_name", "column_names": ["name"]}]


def test_get_indexes_empty(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert db.get_indexes("test") == []


def test_get_show_create_table(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert (
        db.get_show_create_table("test") == "CREATE TABLE test (id INTEGER PRIMARY KEY)"
    )


def test_get_fields(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert db.get_fields("test") == [("id", "INTEGER", 0, None, 1)]


def test_get_charset(db):
    assert db.get_charset() == "UTF-8"


def test_get_collation(db):
    assert db.get_collation() == "UTF-8"


def test_table_simple_info(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert db.table_simple_info() == ["test(id);"]


def test_get_table_info_no_throw(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert db.get_table_info_no_throw("xxxx_table").startswith("Error:")


def test_query_ex(db):
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    db.run("insert into test(id) values (1)")
    db.run("insert into test(id) values (2)")
    field_names, result = db.query_ex("select * from test")
    assert field_names == ["id"]
    assert result == [(1,), (2,)]

    field_names, result = db.query_ex("select * from test", fetch="one")
    assert field_names == ["id"]
    assert result == [(1,)]


def test_query_ex_enforces_sqlite_timeout(db, caplog):
    slow_recursive_query = """
        WITH RECURSIVE counter(value) AS (
            SELECT 1
            UNION ALL
            SELECT value + 1 FROM counter WHERE value < 100000000
        )
        SELECT SUM(value) FROM counter
    """

    with caplog.at_level(logging.INFO, logger="dbgpt.datasource.rdbms.base"):
        with pytest.raises(TimeoutError, match="Query exceeded timeout"):
            db.query_ex(slow_recursive_query, timeout=0.01)
    assert "status=timeout" in caplog.text


def test_query_ex_logs_fingerprint_without_sql_text(db, caplog):
    query = "SELECT 'CONFIDENTIAL_SENTINEL' AS value"

    with caplog.at_level(logging.INFO, logger="dbgpt.datasource.rdbms.base"):
        db.query_ex(query)

    assert query not in caplog.text
    assert sql_fingerprint(query) in caplog.text
    assert "rdbms_sql_audit" in caplog.text
    assert "status=succeeded" in caplog.text
    assert "returned_rows=1" in caplog.text


def test_convert_sql_write_to_select(db):
    # TODO
    pass


def test_get_grants(db):
    assert db.get_grants() == []


def test_get_users(db):
    assert db.get_users() == []


def test_get_table_comments(db):
    assert db.get_table_comments() == []
    db.run("CREATE TABLE test (id INTEGER PRIMARY KEY);")
    assert db.get_table_comments() == [
        ("test", "CREATE TABLE test (id INTEGER PRIMARY KEY)")
    ]


def test_get_database_names(db):
    db.get_database_names() == []


def test_db_dir_exist_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        new_dir = os.path.join(temp_dir, "new_dir")
        file_path = os.path.join(new_dir, "sqlite.db")
        db = SQLiteConnector.from_file_path(file_path)
        assert os.path.exists(new_dir) is True
        assert list(db.get_table_names()) == []
    with tempfile.TemporaryDirectory() as existing_dir:
        file_path = os.path.join(existing_dir, "sqlite.db")
        db = SQLiteConnector.from_file_path(file_path)
        assert os.path.exists(existing_dir) is True
        assert list(db.get_table_names()) == []


def test_db_file_path_without_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    db = SQLiteConnector.from_file_path("relative.db")
    try:
        assert (tmp_path / "relative.db").is_file()
        assert list(db.get_table_names()) == []
    finally:
        db.close()
