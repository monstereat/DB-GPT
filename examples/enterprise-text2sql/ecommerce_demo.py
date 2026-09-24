"""Deterministic, tenant-isolated ecommerce dataset and reference SQL for P0.

This is a business fixture / gold-answer evaluator, NOT a Text-to-SQL model.
It runs against the existing GuardedSQLiteQuery layer and can be invoked by
future DB-GPT integrations to compare generated result sets with gold results.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from guarded_query import GuardedSQLiteQuery


GOLD_QUERIES = {
    "2026 Q2 sales by region": (
        "SELECT region, SUM(revenue) AS sales "
        "FROM orders WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01' "
        "GROUP BY region ORDER BY sales DESC"
    ),
    "2026 Q2 refund amount by region": (
        "SELECT o.region, SUM(r.amount) AS refunded "
        "FROM refunds AS r JOIN orders AS o ON r.order_id = o.id "
        "WHERE r.created_at >= '2026-04-01' AND r.created_at < '2026-07-01' "
        "GROUP BY o.region ORDER BY refunded DESC"
    ),
    "2026 Q2 order count": (
        "SELECT COUNT(*) AS total FROM orders "
        "WHERE created_at >= '2026-04-01' AND created_at < '2026-07-01'"
    ),
}

EXPECTED_TENANT_A = {
    "2026 Q2 sales by region": {
        "columns": ["region", "sales"],
        "rows": [["Guangzhou", 300], ["Shenzhen", 200]],
    },
    "2026 Q2 refund amount by region": {
        "columns": ["region", "refunded"],
        "rows": [["Guangzhou", 30]],
    },
    "2026 Q2 order count": {
        "columns": ["total"],
        "rows": [[3]],
    },
}


def create_demo_database(path: str | Path) -> Path:
    """Create a fixture DB once; never point this at a real application database."""
    db = Path(path)
    if db.exists():
        raise FileExistsError("Refusing to overwrite an existing database")
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                region TEXT NOT NULL,
                created_at TEXT NOT NULL,
                revenue INTEGER NOT NULL,
                internal_note TEXT
            );
            CREATE TABLE refunds (
                id INTEGER PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                amount INTEGER NOT NULL,
                internal_note TEXT
            );
            INSERT INTO orders VALUES
                (1, 'tenant-a', 'Guangzhou', '2026-04-03', 100, 'a-1'),
                (2, 'tenant-a', 'Guangzhou', '2026-05-05', 200, 'a-2'),
                (3, 'tenant-a', 'Shenzhen', '2026-06-18', 200, 'a-3'),
                (4, 'tenant-a', 'Guangzhou', '2026-07-01', 500, 'outside-q2'),
                (5, 'tenant-b', 'Guangzhou', '2026-04-03', 99999, 'b-only');
            INSERT INTO refunds VALUES
                (10, 'tenant-a', 2, '2026-06-19', 30, 'a-refund'),
                (11, 'tenant-b', 5, '2026-06-20', 99999, 'b-refund'),
                (12, 'tenant-a', 1, '2026-07-01', 10, 'outside-q2');
            """
        )
    return db


def tenant_executor(db: str | Path, tenant_id: str) -> GuardedSQLiteQuery:
    """These policies represent server-owned scopes, never LLM-provided input."""
    return GuardedSQLiteQuery(
        db,
        allowed_tables={"orders", "refunds"},
        allowed_columns={
            "orders": {"id", "region", "created_at", "revenue"},
            "refunds": {"id", "order_id", "created_at", "amount"},
        },
        tenant_id=tenant_id,
        tenant_columns={"orders": "tenant_id", "refunds": "tenant_id"},
        max_rows=100,
    )


def evaluate_gold_questions(executor: GuardedSQLiteQuery) -> list[dict]:
    """Measure result equality; these are fixed gold SQL, not model accuracy."""
    report = []
    for question, sql in GOLD_QUERIES.items():
        actual = executor.run(sql)
        expected = EXPECTED_TENANT_A[question]
        report.append({
            "question": question,
            "passed": {
                "columns": actual["columns"],
                "rows": actual["rows"],
            } == expected,
            "returned_rows": actual["returned_rows"],
            "duration_ms": actual["duration_ms"],
        })
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="Path for a NEW demo SQLite file")
    args = parser.parse_args()
    db = create_demo_database(args.database)
    report = evaluate_gold_questions(tenant_executor(db, "tenant-a"))
    print(json.dumps(report, indent=2))
    if not all(item["passed"] for item in report):
        raise SystemExit(1)
