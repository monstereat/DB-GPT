import sqlite3

import pytest
import semantic_metrics
from ecommerce_demo import (
    create_demo_database,
    tenant_executor,
    tenant_gross_margin_executor,
)
from guarded_query import QueryRejected
from semantic_metrics import _validate_dependency_graph, build_metric_query


@pytest.fixture
def executor(tmp_path):
    db = create_demo_database(tmp_path / "ecommerce.sqlite")
    return tenant_executor(db, "tenant-a")


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    [
        (
            "sales_amount",
            [["Guangzhou", 45000], ["Shenzhen", 32000]],
        ),
        (
            "paid_refund_amount",
            [["Guangzhou", 2500], ["Shenzhen", 2200]],
        ),
        (
            "net_sales_amount",
            [["Guangzhou", 42500], ["Shenzhen", 29800]],
        ),
        (
            "refund_rate",
            [["Guangzhou", 5.56], ["Shenzhen", 6.88]],
        ),
    ],
)
def test_versioned_metrics_match_their_registered_definition(
    executor, metric_id, expected
):
    metric_query = build_metric_query(
        metric_id,
        "2026-04-01",
        "2026-07-01",
        dimension="region",
    )

    actual = executor.run(metric_query["sql"])

    assert actual["rows"] == expected
    assert metric_query["metric_id"] == metric_id
    assert metric_query["metric_version"] == "1.0.0"
    assert metric_query["catalog_version"] == "1.2.0"
    assert metric_query["definition"]


def test_metric_date_range_uses_exclusive_end_boundary(executor):
    metric_query = build_metric_query("paid_refund_amount", "2026-06-01", "2026-07-01")

    assert executor.run(metric_query["sql"])["rows"] == [[1500]]


def test_gross_margin_metric_is_role_gated_and_scoped_to_tenant_and_region(
    tmp_path,
):
    db = create_demo_database(tmp_path / "gross-margin.sqlite")
    query = build_metric_query(
        "gross_margin_rate",
        "2026-04-01",
        "2026-07-01",
        dimension="region",
        role="admin",
    )
    executor = tenant_gross_margin_executor(
        db, "tenant-a", role="admin", region_id="a-gz"
    )

    assert executor.run(query["sql"])["rows"] == [["Guangzhou", 48.0]]
    assert "internal_cost_cents" in query["sql"]
    with pytest.raises(ValueError, match="not available to this role"):
        build_metric_query(
            "gross_margin_rate",
            "2026-04-01",
            "2026-07-01",
            role="normal",
        )


def test_raw_tenant_executor_still_rejects_internal_cost(tmp_path):
    db = create_demo_database(tmp_path / "raw-cost.sqlite")
    executor = tenant_executor(db, "tenant-a")

    with pytest.raises(QueryRejected):
        executor.run("SELECT internal_cost_cents FROM products")


def test_gross_margin_returns_null_when_date_range_has_no_sales(tmp_path):
    db = create_demo_database(tmp_path / "gross-margin-zero.sqlite")
    query = build_metric_query(
        "gross_margin_rate",
        "2030-01-01",
        "2030-02-01",
        role="admin",
    )
    executor = tenant_gross_margin_executor(db, "tenant-a", role="admin")

    assert executor.run(query["sql"])["rows"] == [[None]]


def test_metric_version_must_be_explicitly_published(executor):
    default = build_metric_query(
        "net_sales_amount", "2026-04-01", "2026-07-01", dimension="region"
    )
    selected = build_metric_query(
        "net_sales_amount",
        "2026-04-01",
        "2026-07-01",
        dimension="region",
        metric_version="1.0.0",
    )

    assert selected["metric_version"] == "1.0.0"
    assert selected["sql"] == default["sql"]
    assert executor.run(selected["sql"])["rows"] == [
        ["Guangzhou", 42500],
        ["Shenzhen", 29800],
    ]
    with pytest.raises(ValueError, match="not published"):
        build_metric_query(
            "net_sales_amount",
            "2026-04-01",
            "2026-07-01",
            metric_version="0.9.0",
        )


def test_paid_refund_versions_use_distinct_period_definitions(executor):
    refund_date_metric = build_metric_query(
        "paid_refund_amount", "2026-05-09", "2026-05-11", metric_version="1.0.0"
    )
    order_cohort_metric = build_metric_query(
        "paid_refund_amount", "2026-05-09", "2026-05-11", metric_version="2.0.0"
    )

    assert executor.run(refund_date_metric["sql"])["rows"] == [[2000]]
    assert executor.run(order_cohort_metric["sql"])["rows"] == [[None]]
    assert refund_date_metric["definition"] != order_cohort_metric["definition"]
    assert "o.created_at" in order_cohort_metric["sql"]


def test_net_sales_cohort_version_pins_order_cohort_refund_definition(tmp_path):
    database = create_demo_database(tmp_path / "cohort.sqlite")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "tenant-a",
                99,
                1,
                "2026-07-03",
                1000,
                "paid",
                "synthetic cohort boundary",
            ),
        )
    executor = tenant_executor(database, "tenant-a")

    refund_date_metric = build_metric_query(
        "net_sales_amount", "2026-04-01", "2026-07-01", metric_version="1.0.0"
    )
    order_cohort_metric = build_metric_query(
        "net_sales_amount", "2026-04-01", "2026-07-01", metric_version="2.0.0"
    )

    assert executor.run(refund_date_metric["sql"])["rows"] == [[72300]]
    assert executor.run(order_cohort_metric["sql"])["rows"] == [[71300]]
    assert "cohort" in order_cohort_metric["definition"]
    assert "o.created_at" in order_cohort_metric["sql"]


def test_refund_rate_versions_compare_refund_date_and_order_cohort(tmp_path):
    database = create_demo_database(tmp_path / "refund-rate-cohort.sqlite")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "tenant-a",
                99,
                1,
                "2026-07-03",
                1000,
                "paid",
                "synthetic cohort boundary",
            ),
        )
    executor = tenant_executor(database, "tenant-a")

    refund_date_metric = build_metric_query(
        "refund_rate", "2026-04-01", "2026-07-01", metric_version="1.0.0"
    )
    order_cohort_metric = build_metric_query(
        "refund_rate", "2026-04-01", "2026-07-01", metric_version="2.0.0"
    )

    assert executor.run(refund_date_metric["sql"])["rows"] == [[6.1]]
    assert executor.run(order_cohort_metric["sql"])["rows"] == [[7.4]]
    assert "cohort" in order_cohort_metric["definition"]


@pytest.mark.parametrize(
    ("metric_id", "expected"),
    [
        (
            "sales_amount",
            [["2026-04", 10000], ["2026-05", 32000], ["2026-06", 35000]],
        ),
        (
            "paid_refund_amount",
            [["2026-05", 3200], ["2026-06", 1500]],
        ),
        (
            "net_sales_amount",
            [["2026-04", 10000], ["2026-05", 28800], ["2026-06", 33500]],
        ),
        (
            "refund_rate",
            [["2026-04", 0.0], ["2026-05", 10.0], ["2026-06", 4.29]],
        ),
    ],
)
def test_monthly_metrics_match_registered_period_semantics(
    executor, metric_id, expected
):
    metric_query = build_metric_query(
        metric_id,
        "2026-04-01",
        "2026-07-01",
        dimension="month",
    )

    actual = executor.run(metric_query["sql"])

    expected_column = {
        "sales_amount": "sales_cents",
        "paid_refund_amount": "refunded_cents",
        "net_sales_amount": "net_sales_cents",
        "refund_rate": "refund_rate_pct",
    }[metric_id]
    assert actual["columns"] == ["period", expected_column]
    assert actual["rows"] == expected
    assert metric_query["dimension"] == "month"


@pytest.mark.parametrize(
    ("metric_id", "start_date", "end_date", "dimension"),
    [
        ("unknown_metric", "2026-04-01", "2026-07-01", None),
        ("sales_amount", "2026-04-01", "2026-07-01", "email"),
        ("sales_amount", "2026-7-1", "2026-10-01", None),
        ("sales_amount", "2026-07-01", "2026-04-01", None),
    ],
)
def test_metric_builder_rejects_unregistered_inputs(
    metric_id, start_date, end_date, dimension
):
    with pytest.raises(ValueError):
        build_metric_query(metric_id, start_date, end_date, dimension=dimension)


def test_metric_dependency_graph_accepts_nested_acyclic_versions():
    metrics = {
        "source": {"1.0.0": {"dependencies": []}},
        "derived": {
            "1.0.0": {
                "dependencies": ["source"],
                "dependency_versions": {"source": "1.0.0"},
            }
        },
        "top_level": {
            "1.0.0": {
                "dependencies": ["derived", "source"],
                "dependency_versions": {"derived": "1.0.0", "source": "1.0.0"},
            }
        },
    }

    _validate_dependency_graph(metrics)


def test_metric_dependency_graph_rejects_versioned_cycles():
    metrics = {
        "first": {
            "1.0.0": {
                "dependencies": ["second"],
                "dependency_versions": {"second": "1.0.0"},
            }
        },
        "second": {
            "1.0.0": {
                "dependencies": ["first"],
                "dependency_versions": {"first": "1.0.0"},
            }
        },
    }

    with pytest.raises(ValueError, match="contains a cycle"):
        _validate_dependency_graph(metrics)


@pytest.mark.parametrize(
    ("dimension", "expected"),
    [
        (None, [[4700]]),
        ("region", [["Guangzhou", 2500], ["Shenzhen", 2200]]),
    ],
)
def test_nested_derived_metrics_compile_and_execute(
    executor, monkeypatch, dimension, expected
):
    metric_id = "sales_minus_cohort_net_sales"
    metric = {
        "id": metric_id,
        "version": "1.0.0",
        "name": "销售额与 cohort 净销售额差额",
        "calculation": "subtract",
        "dependencies": ["sales_amount", "net_sales_amount"],
        "dependency_versions": {
            "sales_amount": "1.0.0",
            "net_sales_amount": "2.0.0",
        },
        "unit": "CNY_cent",
        "definition": "测试递归编译固定版本依赖。",
    }
    monkeypatch.setitem(semantic_metrics._METRICS, metric_id, {"1.0.0": metric})
    monkeypatch.setitem(semantic_metrics._DEFAULT_METRIC_VERSIONS, metric_id, "1.0.0")
    monkeypatch.setitem(semantic_metrics._OUTPUT_COLUMNS, metric_id, "difference_cents")

    query = build_metric_query(
        metric_id,
        "2026-04-01",
        "2026-07-01",
        dimension=dimension,
    )

    assert query["sql"].count(" AS (") == 4
    assert executor.run(query["sql"])["rows"] == expected
