import sqlite3

import pytest

from guarded_query import GuardedSQLiteQuery, QueryRejected


@pytest.fixture
def executor(tmp_path):
    db_path = tmp_path / "sales.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                region TEXT,
                revenue INTEGER,
                internal_note TEXT
            );
            INSERT INTO orders (region, revenue, internal_note)
                VALUES
                ('Guangzhou', 100, 'secret-a'),
                ('Shenzhen', 200, 'secret-b'),
                ('Dongguan', 80, 'secret-c');
            CREATE TABLE private_payroll (employee TEXT, salary INTEGER);
            INSERT INTO private_payroll VALUES ('admin', 99999);
            """
        )
    return GuardedSQLiteQuery(
        db_path,
        {"orders"},
        allowed_columns={"orders": {"id", "region", "revenue"}},
        max_rows=2,
    )


def test_aggregated_read_only_sql(executor):
    result = executor.run("SELECT SUM(revenue) AS total FROM orders")
    assert result["columns"] == ["total"]
    assert result["rows"] == [[380]]
    assert result["returned_rows"] == 1
    assert result["duration_ms"] >= 0


def test_cte_and_limit_are_supported(executor):
    result = executor.run(
        "WITH regional AS (SELECT region, revenue FROM orders) "
        "SELECT region FROM regional ORDER BY revenue DESC"
    )
    assert result["rows"] == [["Shenzhen"], ["Guangzhou"]]


def test_limit_applies_even_when_model_requests_more(executor):
    assert executor.run("SELECT id FROM orders ORDER BY id LIMIT 100")["returned_rows"] == 2


def test_column_policy_blocks_sensitive_fields(executor):
    with pytest.raises(QueryRejected):
        executor.run("SELECT internal_note FROM orders")


def test_select_star_is_rejected_when_it_reaches_denied_column(executor):
    with pytest.raises(QueryRejected):
        executor.run("SELECT * FROM orders")


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


def test_column_policy_cannot_escape_table_policy(tmp_path):
    db = tmp_path / "empty.sqlite"
    sqlite3.connect(db).close()
    with pytest.raises(ValueError):
        GuardedSQLiteQuery(
            db,
            {"orders"},
            allowed_columns={"private_payroll": {"salary"}},
        )


def test_audit_event_contains_hash_not_raw_sql(tmp_path):
    db = tmp_path / "audit.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("CREATE TABLE orders (id INTEGER); INSERT INTO orders VALUES (1);")

    events = []
    executor = GuardedSQLiteQuery(db, {"orders"}, audit_sink=events.append)
    executor.run("SELECT id FROM orders")

    assert len(events) == 1
    event = events[0]
    assert event["status"] == "succeeded"
    assert event["returned_rows"] == 1
    assert event["allowed_tables"] == ["orders"]
    assert len(event["query_sha256"]) == 64
    assert "sql" not in event


def test_tenant_scope_filters_rows_and_blocks_direct_main_table_access(tmp_path):
    db = tmp_path / "tenant.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                region TEXT,
                revenue INTEGER,
                internal_note TEXT
            );
            INSERT INTO orders (tenant_id, region, revenue, internal_note) VALUES
                ('tenant-a', 'Guangzhou', 100, 'a-only'),
                ('tenant-b', 'Shanghai', 900, 'b-only'),
                ('tenant-a', 'Shenzhen', 200, 'a-only-2');
            """
        )

    tenant_a = GuardedSQLiteQuery(
        db,
        {"orders"},
        allowed_columns={"orders": {"id", "region", "revenue"}},
        tenant_id="tenant-a",
        tenant_columns={"orders": "tenant_id"},
        max_rows=10,
    )

    result = tenant_a.run("SELECT region, revenue FROM orders ORDER BY id")
    assert result["rows"] == [["Guangzhou", 100], ["Shenzhen", 200]]

    with pytest.raises(QueryRejected):
        tenant_a.run("SELECT region FROM main.orders")


def test_tenant_scope_does_not_expose_tenant_or_sensitive_columns(tmp_path):
    db = tmp_path / "tenant-columns.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER,
                tenant_id TEXT,
                revenue INTEGER,
                internal_note TEXT
            );
            INSERT INTO orders VALUES (1, 'tenant-a', 100, 'secret');
            """
        )

    executor = GuardedSQLiteQuery(
        db,
        {"orders"},
        allowed_columns={"orders": {"id", "revenue"}},
        tenant_id="tenant-a",
        tenant_columns={"orders": "tenant_id"},
    )
    assert executor.run("SELECT id, revenue FROM orders")["rows"] == [[1, 100]]

    for query in (
        "SELECT tenant_id FROM orders",
        "SELECT internal_note FROM orders",
        "SELECT * FROM orders",
    ):
        with pytest.raises(QueryRejected):
            executor.run(query)


def test_tenant_mode_requires_complete_server_side_policy(tmp_path):
    db = tmp_path / "tenant-policy.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            "CREATE TABLE orders (tenant_id TEXT, id INTEGER);"
            "CREATE TABLE refunds (tenant_id TEXT, id INTEGER);"
        )

    with pytest.raises(ValueError):
        GuardedSQLiteQuery(
            db,
            {"orders", "refunds"},
            allowed_columns={"orders": {"id"}, "refunds": {"id"}},
            tenant_id="tenant-a",
            tenant_columns={"orders": "tenant_id"},
        )

    with pytest.raises(ValueError):
        GuardedSQLiteQuery(
            db,
            {"orders"},
            tenant_id="tenant-a",
            tenant_columns={"orders": "tenant_id"},
        )
