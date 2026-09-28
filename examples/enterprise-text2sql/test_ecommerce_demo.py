"""Golden dataset checks for tenant isolation and deterministic metric results."""

import sqlite3

import pytest
from ecommerce_demo import (
    _TABLE_COLUMNS,
    GOLD_QUERIES,
    SCHEMA_METADATA,
    create_demo_database,
    evaluate_gold_questions,
    tenant_executor,
)
from guarded_query import QueryRejected


@pytest.fixture
def db(tmp_path):
    return create_demo_database(tmp_path / "ecommerce.sqlite")


def test_gold_questions_match_tenant_a_answers(db):
    report = evaluate_gold_questions(tenant_executor(db, "tenant-a"))
    assert len(report) == len(GOLD_QUERIES)
    assert len(report) == 50
    assert all(result["passed"] for result in report)


def test_second_tenant_only_sees_own_orders(db):
    executor = tenant_executor(db, "tenant-b")
    assert executor.run(GOLD_QUERIES["q03"])["rows"] == [[1]]
    sales = executor.run(GOLD_QUERIES["q01"])
    assert sales["rows"] == [["Guangzhou", 999999]]


def test_fixture_has_the_six_documented_business_tables(db):
    with sqlite3.connect(db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert tables == {
        "users",
        "regions",
        "products",
        "orders",
        "order_items",
        "refunds",
    }


def test_machine_readable_schema_matches_fixture_and_foreign_keys(db):
    metadata_tables = {table["name"]: table for table in SCHEMA_METADATA["tables"]}
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        actual_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert actual_tables == set(metadata_tables)

        actual_relations = set()
        for table_name, metadata in metadata_tables.items():
            actual_columns = {
                row["name"]
                for row in conn.execute(f'PRAGMA table_info("{table_name}")')
            }
            documented_columns = {column["name"] for column in metadata["columns"]}
            assert actual_columns == documented_columns

            foreign_keys = {}
            for row in conn.execute(f'PRAGMA foreign_key_list("{table_name}")'):
                foreign_keys.setdefault(row["id"], []).append(row)
            for rows in foreign_keys.values():
                rows.sort(key=lambda row: row["seq"])
                actual_relations.add(
                    (
                        table_name,
                        tuple(row["from"] for row in rows),
                        rows[0]["table"],
                        tuple(row["to"] for row in rows),
                    )
                )

    documented_relations = {
        (
            relation["child_table"],
            tuple(relation["child_columns"]),
            relation["parent_table"],
            tuple(relation["parent_columns"]),
        )
        for relation in SCHEMA_METADATA["relations"]
    }
    assert actual_relations == documented_relations


def test_query_allowlists_come_from_schema_metadata():
    for table in SCHEMA_METADATA["tables"]:
        queryable = {
            column["name"] for column in table["columns"] if column["agent_queryable"]
        }
        assert _TABLE_COLUMNS[table["name"]] == queryable
        assert "tenant_id" not in queryable
    assert SCHEMA_METADATA["source"]["read_only_queries"] is True


def test_tenant_views_prevent_cross_tenant_join_rows(db):
    result = tenant_executor(db, "tenant-a").run(
        "SELECT r.name, SUM(o.total_cents) FROM orders o "
        "JOIN regions r ON r.region_id = o.region_id GROUP BY r.name"
    )
    assert result["rows"] == [["Guangzhou", 95000], ["Shenzhen", 45000]]


def test_region_scope_filters_direct_and_related_tables(db):
    executor = tenant_executor(db, "tenant-a", region_id="a-gz")

    orders = executor.run("SELECT order_id FROM orders ORDER BY order_id")
    products = executor.run("SELECT product_id FROM products ORDER BY product_id")
    refunds = executor.run("SELECT refund_id FROM refunds ORDER BY refund_id")

    assert orders["rows"] == [[1], [2], [4], [8]]
    assert products["rows"] == [["a-p1"], ["a-p2"], ["a-p3"]]
    assert refunds["rows"] == [[1], [4], [5]]


def test_region_scope_cannot_be_used_to_read_another_tenants_rows(db):
    executor = tenant_executor(db, "tenant-a", region_id="b-gz")

    assert executor.run("SELECT order_id FROM orders")["rows"] == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT email FROM users",
        "SELECT phone FROM users",
        "SELECT internal_cost_cents FROM products",
        "SELECT internal_note FROM refunds",
        "SELECT tenant_id FROM orders",
    ],
)
def test_sensitive_columns_are_not_exposed(db, query):
    with pytest.raises(QueryRejected):
        tenant_executor(db, "tenant-a").run(query)


def test_unknown_tenant_policy_fails_closed(db):
    with pytest.raises(ValueError, match="Unknown demo tenant"):
        tenant_executor(db, "tenant-c")


@pytest.mark.parametrize(
    "query",
    [
        "SELECT tenant_id FROM orders",
        "SELECT internal_note FROM orders",
        "SELECT * FROM main.orders",
        "UPDATE orders SET revenue = 1",
    ],
)
def test_denies_sensitive_data_and_direct_table_bypass(db, query):
    with pytest.raises(QueryRejected):
        tenant_executor(db, "tenant-a").run(query)


def test_fixture_does_not_overwrite_existing_data(db):
    with pytest.raises(FileExistsError):
        create_demo_database(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone() == (9,)
