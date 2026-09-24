import sqlite3

import pytest

from guarded_query import GuardedSQLiteQuery, QueryRejected


@pytest.fixture
def executor(tmp_path):
    db_path = tmp_path / "sales.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (id INTEGER PRIMARY KEY, region TEXT, revenue INTEGER);
            INSERT INTO orders (region, revenue)
                VALUES ('Guangzhou', 100), ('Shenzhen', 200), ('Dongguan', 80);
            CREATE TABLE private_payroll (employee TEXT, salary INTEGER);
            INSERT INTO private_payroll VALUES ('admin', 99999);
            """
        )
    return GuardedSQLiteQuery(db_path, {"orders"}, max_rows=2)


def test_aggregated_read_only_sql(executor):
    result = executor.run("SELECT SUM(revenue) AS total FROM orders")
    assert result == {"columns": ["total"], "rows": [[380]], "returned_rows": 1}


def test_cte_and_limit_are_supported(executor):
    result = executor.run(
        "WITH regional AS (SELECT region, revenue FROM orders) "
        "SELECT region FROM regional ORDER BY revenue DESC"
    )
    assert result["rows"] == [["Shenzhen"], ["Guangzhou"]]


def test_limit_applies_even_when_model_requests_more(executor):
    assert executor.run("SELECT id FROM orders ORDER BY id LIMIT 100")["returned_rows"] == 2


@pytest.mark.parametrize(
    "unsafe_sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET revenue = 0",
        "PRAGMA table_info(orders)",
        "SELECT * FROM private_payroll",
        "SELECT * FROM orders; DELETE FROM orders",
        "SELECT load_extension('unsafe')",
        "WITH removed AS (DELETE FROM orders RETURNING *) SELECT * FROM removed",
    ],
)
def test_fail_closed_on_unsafe_or_unauthorized_sql(executor, unsafe_sql):
    with pytest.raises(QueryRejected):
        executor.run(unsafe_sql)


def test_database_was_not_modified(executor):
    with pytest.raises(QueryRejected):
        executor.run("UPDATE orders SET revenue = 0")
    assert executor.run("SELECT SUM(revenue) FROM orders")["rows"] == [[380]]


def test_requires_server_supplied_table_scope(tmp_path):
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()
    with pytest.raises(ValueError):
        GuardedSQLiteQuery(db, set())
