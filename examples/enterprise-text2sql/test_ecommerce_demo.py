"""Golden dataset checks for tenant isolation and deterministic metric results."""

import sqlite3

import pytest

from ecommerce_demo import (
    GOLD_QUERIES,
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
    assert all(result["passed"] for result in report)


def test_second_tenant_only_sees_own_orders(db):
    executor = tenant_executor(db, "tenant-b")
    assert executor.run(GOLD_QUERIES["2026 Q2 order count"])["rows"] == [[1]]
    sales = executor.run(GOLD_QUERIES["2026 Q2 sales by region"])
    assert sales["rows"] == [["Guangzhou", 99999]]


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
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone() == (5,)
