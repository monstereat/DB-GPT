"""Synthetic multi-tenant ecommerce fixture and deterministic gold answers.

The fixture is isolated demo data. It is never used as, or copied into, an
application database. Every exposed table is scoped by a server-owned tenant
policy through :class:`GuardedSQLiteQuery`.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from guarded_query import GuardedSQLiteQuery

GOLD_QUESTIONS = json.loads(
    Path(__file__).with_name("gold_questions.json").read_text(encoding="utf-8")
)
GOLD_QUERIES = {item["id"]: item["sql"] for item in GOLD_QUESTIONS}
EXPECTED_TENANT_A = {item["id"]: item["expected"] for item in GOLD_QUESTIONS}
GOLD_ORDER_SENSITIVE = {item["id"]: item["order_sensitive"] for item in GOLD_QUESTIONS}
if any(not isinstance(item.get("order_sensitive"), bool) for item in GOLD_QUESTIONS):
    raise ValueError("Every gold question must declare order_sensitive")


def gold_rows_match(
    question_id: str,
    actual_rows: list,
    expected_rows: list,
    order_sensitive: bool | None = None,
) -> bool:
    """Compare result rows according to the question's declared semantics."""
    if order_sensitive is None:
        order_sensitive = GOLD_ORDER_SENSITIVE.get(question_id, True)
    if order_sensitive:
        return actual_rows == expected_rows
    try:
        return Counter(tuple(row) for row in actual_rows) == Counter(
            tuple(row) for row in expected_rows
        )
    except TypeError:
        return False


def _load_schema_metadata() -> dict:
    """Load and validate the server-owned source and table policy metadata."""
    metadata = json.loads(
        Path(__file__).with_name("schema_metadata.json").read_text(encoding="utf-8")
    )
    source = metadata.get("source", {})
    if (
        source.get("id") != "synthetic-ecommerce"
        or source.get("driver") != "sqlite"
        or source.get("purpose") != "local-demo-and-regression-only"
        or source.get("read_only_queries") is not True
        or source.get("tenant_column") != "tenant_id"
        or not source.get("policy_version")
    ):
        raise ValueError("Invalid or unsafe demo data source metadata")

    tables = metadata.get("tables")
    if not isinstance(tables, list) or not tables:
        raise ValueError("Schema metadata must define at least one table")
    table_names = [table.get("name") for table in tables]
    if len(set(table_names)) != len(table_names):
        raise ValueError("Schema metadata contains duplicate table names")

    classifications = {"tenant_key", "business", "personal", "confidential"}
    for table in tables:
        if not isinstance(table.get("description"), str) or not table["description"]:
            raise ValueError("Every schema table must have a description")
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            raise ValueError("Every schema table must define columns")
        column_names = [column.get("name") for column in columns]
        if len(set(column_names)) != len(column_names):
            raise ValueError("Schema metadata contains duplicate column names")
        tenant_columns = [
            column
            for column in columns
            if column.get("name") == source["tenant_column"]
        ]
        if (
            len(tenant_columns) != 1
            or tenant_columns[0].get("classification") != "tenant_key"
            or tenant_columns[0].get("agent_queryable") is not False
        ):
            raise ValueError("Every table must hide its tenant isolation key")
        for column in columns:
            if (
                column.get("classification") not in classifications
                or not isinstance(column.get("description"), str)
                or not column["description"]
            ):
                raise ValueError(
                    "Schema columns require a description and classification"
                )
            if (
                column.get("classification")
                in {
                    "tenant_key",
                    "personal",
                    "confidential",
                }
                and column.get("agent_queryable") is not False
            ):
                raise ValueError("Sensitive schema columns must be non-queryable")
            if not isinstance(column.get("agent_queryable"), bool):
                raise ValueError("Schema columns must explicitly define query access")

    known_tables = set(table_names)
    columns_by_table = {
        table["name"]: {column["name"] for column in table["columns"]}
        for table in tables
    }
    queryable_columns = {
        table["name"]: {
            column["name"] for column in table["columns"] if column["agent_queryable"]
        }
        for table in tables
    }
    region_scope = source.get("region_scope", {})
    region_scope_tables = set().union(
        *(
            set(region_scope.get(key, {}))
            for key in ("direct", "via_orders", "via_order_items")
        )
    )
    if region_scope_tables != known_tables:
        raise ValueError("Every schema table needs an explicit region scope rule")
    for policy_name in ("direct", "via_orders", "via_order_items"):
        for table, column in region_scope.get(policy_name, {}).items():
            if column not in queryable_columns.get(table, set()):
                raise ValueError("Region scope must use queryable schema columns")
    if region_scope.get("via_orders", {}).keys() != {
        "order_items",
        "refunds",
    } or region_scope.get("via_order_items", {}).keys() != {"products"}:
        raise ValueError("Region scope relationships do not match the demo schema")
    for relation in metadata.get("relations", []):
        child = relation.get("child_table")
        parent = relation.get("parent_table")
        child_columns = relation.get("child_columns")
        parent_columns = relation.get("parent_columns")
        if (
            child not in known_tables
            or parent not in known_tables
            or not isinstance(child_columns, list)
            or not isinstance(parent_columns, list)
            or not child_columns
            or len(child_columns) != len(parent_columns)
            or set(child_columns) - columns_by_table[child]
            or set(parent_columns) - columns_by_table[parent]
            or source["tenant_column"] not in child_columns
            or source["tenant_column"] not in parent_columns
        ):
            raise ValueError(
                "Schema metadata contains an invalid tenant-scoped relation"
            )
    return metadata


SCHEMA_METADATA = _load_schema_metadata()
_TABLES = {table["name"]: table for table in SCHEMA_METADATA["tables"]}
_TABLE_COLUMNS = {
    table_name: {
        column["name"] for column in table["columns"] if column["agent_queryable"]
    }
    for table_name, table in _TABLES.items()
}
_TENANT_COLUMNS = {
    table_name: SCHEMA_METADATA["source"]["tenant_column"] for table_name in _TABLES
}


def create_demo_database(path: str | Path) -> Path:
    """Create a new six-table fixture; refuse to overwrite any existing file."""
    db = Path(path)
    if db.exists():
        raise FileExistsError("Refusing to overwrite an existing database")
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE regions (
                tenant_id TEXT NOT NULL, region_id TEXT NOT NULL,
                name TEXT NOT NULL, area TEXT NOT NULL,
                PRIMARY KEY (tenant_id, region_id)
            );
            CREATE TABLE users (
                tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                region_id TEXT NOT NULL, full_name TEXT NOT NULL,
                email TEXT NOT NULL, phone TEXT NOT NULL,
                PRIMARY KEY (tenant_id, user_id),
                FOREIGN KEY (tenant_id, region_id)
                    REFERENCES regions (tenant_id, region_id)
            );
            CREATE TABLE products (
                tenant_id TEXT NOT NULL, product_id TEXT NOT NULL,
                product_name TEXT NOT NULL, category TEXT NOT NULL,
                list_price_cents INTEGER NOT NULL,
                internal_cost_cents INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, product_id)
            );
            CREATE TABLE orders (
                tenant_id TEXT NOT NULL, order_id INTEGER NOT NULL,
                user_id TEXT NOT NULL, region_id TEXT NOT NULL,
                created_at TEXT NOT NULL, status TEXT NOT NULL,
                total_cents INTEGER NOT NULL, internal_note TEXT,
                PRIMARY KEY (tenant_id, order_id),
                FOREIGN KEY (tenant_id, user_id)
                    REFERENCES users (tenant_id, user_id),
                FOREIGN KEY (tenant_id, region_id)
                    REFERENCES regions (tenant_id, region_id)
            );
            CREATE TABLE order_items (
                tenant_id TEXT NOT NULL, item_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL, product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL, unit_price_cents INTEGER NOT NULL,
                PRIMARY KEY (tenant_id, item_id),
                FOREIGN KEY (tenant_id, order_id)
                    REFERENCES orders (tenant_id, order_id),
                FOREIGN KEY (tenant_id, product_id)
                    REFERENCES products (tenant_id, product_id)
            );
            CREATE TABLE refunds (
                tenant_id TEXT NOT NULL, refund_id INTEGER NOT NULL,
                order_id INTEGER NOT NULL, created_at TEXT NOT NULL,
                amount_cents INTEGER NOT NULL, status TEXT NOT NULL,
                internal_note TEXT,
                PRIMARY KEY (tenant_id, refund_id),
                FOREIGN KEY (tenant_id, order_id)
                    REFERENCES orders (tenant_id, order_id)
            );
            """
        )
        conn.executemany(
            "INSERT INTO regions VALUES (?, ?, ?, ?)",
            [
                ("tenant-a", "a-gz", "Guangzhou", "South China"),
                ("tenant-a", "a-sz", "Shenzhen", "South China"),
                ("tenant-b", "b-gz", "Guangzhou", "South China"),
            ],
        )
        conn.executemany(
            "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    "tenant-a",
                    "a-u1",
                    "a-gz",
                    "Synthetic User 1",
                    "u1@example.test",
                    "10000000001",
                ),
                (
                    "tenant-a",
                    "a-u2",
                    "a-gz",
                    "Synthetic User 2",
                    "u2@example.test",
                    "10000000002",
                ),
                (
                    "tenant-a",
                    "a-u3",
                    "a-sz",
                    "Synthetic User 3",
                    "u3@example.test",
                    "10000000003",
                ),
                (
                    "tenant-b",
                    "b-u1",
                    "b-gz",
                    "Other Tenant User",
                    "b1@example.test",
                    "20000000001",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("tenant-a", "a-p1", "Phone", "Electronics", 10000, 6000),
                ("tenant-a", "a-p2", "Case", "Accessories", 5000, 1200),
                ("tenant-a", "a-p3", "Chair", "Furniture", 15000, 9000),
                ("tenant-a", "a-p4", "Tablet", "Electronics", 8000, 5000),
                ("tenant-b", "b-p1", "Private Product", "Electronics", 999999, 1),
            ],
        )
        conn.executemany(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "tenant-a",
                    1,
                    "a-u1",
                    "a-gz",
                    "2026-04-03",
                    "completed",
                    10000,
                    "internal a1",
                ),
                (
                    "tenant-a",
                    2,
                    "a-u2",
                    "a-gz",
                    "2026-05-05",
                    "completed",
                    20000,
                    "internal a2",
                ),
                (
                    "tenant-a",
                    3,
                    "a-u1",
                    "a-sz",
                    "2026-06-18",
                    "completed",
                    20000,
                    "internal a3",
                ),
                (
                    "tenant-a",
                    4,
                    "a-u3",
                    "a-gz",
                    "2026-07-01",
                    "completed",
                    50000,
                    "outside q2",
                ),
                (
                    "tenant-a",
                    5,
                    "a-u3",
                    "a-sz",
                    "2025-04-03",
                    "completed",
                    8000,
                    "prior year",
                ),
                (
                    "tenant-a",
                    6,
                    "a-u2",
                    "a-sz",
                    "2026-04-14",
                    "cancelled",
                    5000,
                    "cancelled",
                ),
                (
                    "tenant-a",
                    7,
                    "a-u2",
                    "a-sz",
                    "2026-05-21",
                    "completed",
                    12000,
                    "internal a7",
                ),
                (
                    "tenant-a",
                    8,
                    "a-u1",
                    "a-gz",
                    "2026-06-29",
                    "completed",
                    15000,
                    "internal a8",
                ),
                (
                    "tenant-b",
                    1,
                    "b-u1",
                    "b-gz",
                    "2026-04-03",
                    "completed",
                    999999,
                    "tenant b",
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO order_items VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("tenant-a", 1, 1, "a-p1", 1, 10000),
                ("tenant-a", 2, 2, "a-p1", 1, 10000),
                ("tenant-a", 3, 2, "a-p2", 2, 5000),
                ("tenant-a", 4, 3, "a-p3", 2, 10000),
                ("tenant-a", 5, 4, "a-p1", 5, 10000),
                ("tenant-a", 6, 5, "a-p4", 1, 8000),
                ("tenant-a", 7, 6, "a-p2", 1, 5000),
                ("tenant-a", 8, 7, "a-p2", 2, 6000),
                ("tenant-a", 9, 8, "a-p3", 1, 15000),
                ("tenant-b", 1, 1, "b-p1", 1, 999999),
            ],
        )
        conn.executemany(
            "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("tenant-a", 1, 2, "2026-05-10", 2000, "paid", "private refund"),
                ("tenant-a", 2, 3, "2026-06-19", 1000, "paid", "private refund"),
                ("tenant-a", 3, 7, "2026-05-25", 1200, "paid", "private refund"),
                ("tenant-a", 4, 8, "2026-06-30", 500, "paid", "private refund"),
                ("tenant-a", 5, 4, "2026-07-02", 1000, "paid", "outside q2"),
                ("tenant-b", 1, 1, "2026-04-03", 99999, "paid", "tenant b"),
            ],
        )
    return db


def tenant_executor(
    db: str | Path,
    tenant_id: str,
    *,
    region_id: str | None = None,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> GuardedSQLiteQuery:
    """Build a policy-scoped executor; tenant ID must come from trusted server code."""
    if tenant_id not in {"tenant-a", "tenant-b"}:
        raise ValueError("Unknown demo tenant")
    region_scope = SCHEMA_METADATA["source"]["region_scope"]
    return GuardedSQLiteQuery(
        db,
        allowed_tables=set(_TABLE_COLUMNS),
        allowed_columns=_TABLE_COLUMNS,
        tenant_id=tenant_id,
        tenant_columns=_TENANT_COLUMNS,
        region_id=region_id,
        region_columns=region_scope["direct"],
        order_scope_columns=region_scope["via_orders"],
        product_scope_columns=region_scope["via_order_items"],
        max_rows=100,
        audit_sink=audit_sink,
    )


def tenant_gross_margin_executor(
    db: str | Path,
    tenant_id: str,
    *,
    role: str,
    region_id: str | None = None,
    audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> GuardedSQLiteQuery:
    """Build a metric-only executor that grants the admin cost calculation."""
    if role != "admin":
        raise ValueError("Gross margin access requires the admin role")
    # Reuse the ordinary policy constructor for tenant and region validation.
    tenant_executor(db, tenant_id, region_id=region_id, audit_sink=audit_sink)
    tables = {"orders", "order_items", "products", "regions"}
    columns = {table: set(_TABLE_COLUMNS[table]) for table in tables}
    columns["products"].add("internal_cost_cents")
    region_scope = SCHEMA_METADATA["source"]["region_scope"]
    return GuardedSQLiteQuery(
        db,
        allowed_tables=tables,
        allowed_columns=columns,
        tenant_id=tenant_id,
        tenant_columns={table: _TENANT_COLUMNS[table] for table in tables},
        region_id=region_id,
        region_columns={
            table: column
            for table, column in region_scope["direct"].items()
            if table in tables
        },
        order_scope_columns={
            table: column
            for table, column in region_scope["via_orders"].items()
            if table in tables
        },
        product_scope_columns={
            table: column
            for table, column in region_scope["via_order_items"].items()
            if table in tables
        },
        max_rows=100,
        audit_sink=audit_sink,
    )


def evaluate_gold_questions(executor: GuardedSQLiteQuery) -> list[dict]:
    """Measure fixed SQL result equality; this is not an LLM benchmark."""
    report = []
    for question, sql in GOLD_QUERIES.items():
        actual = executor.run(sql)
        expected = EXPECTED_TENANT_A[question]
        report.append(
            {
                "question": question,
                "passed": actual["columns"] == expected["columns"]
                and gold_rows_match(question, actual["rows"], expected["rows"]),
                "returned_rows": actual["returned_rows"],
                "duration_ms": actual["duration_ms"],
            }
        )
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database", required=True, help="Path for a NEW synthetic SQLite DB"
    )
    args = parser.parse_args()
    db = create_demo_database(args.database)
    report = evaluate_gold_questions(tenant_executor(db, "tenant-a"))
    print(json.dumps(report, indent=2))
    if not all(item["passed"] for item in report):
        raise SystemExit(1)
