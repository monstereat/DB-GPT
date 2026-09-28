import json
import sqlite3

import pytest

from dbgpt_app.openapi.api_v1.tools.metric_query import (
    _compile_metric_sql,
    make_metric_query,
)


def _sales_catalog():
    return {
        "default_metric_versions": {"sales_amount": "1.0.0"},
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "status": "published",
                "calculation": "sum",
                "source_table": "orders",
                "amount_column": "total_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "completed",
                "period_table": "orders",
                "period_date_column": "created_at",
            }
        ],
        "dimensions": {
            "region": {
                "table": "regions",
                "column": "name",
                "join_column": "region_id",
            }
        },
    }


def test_regional_metric_uses_tenant_composite_join_and_completed_orders():
    query = _compile_metric_sql(
        _sales_catalog(),
        "sales_amount",
        "2026-04-01",
        "2026-07-01",
        dialect="sqlite",
        dimension="region",
        role="normal",
    )

    assert "r.tenant_id=o.tenant_id AND r.region_id=o.region_id" in query["sql"]
    assert "o.status = 'completed'" in query["sql"]
    assert "metric_0.amount AS sales_cents" in query["sql"]
    assert "ORDER BY metric_0.amount DESC, metric_0.region" in query["sql"]


def test_refund_region_metric_joins_order_on_tenant_and_order_ids():
    catalog = _sales_catalog()
    metric = catalog["metrics"][0]
    metric.update(
        {
            "id": "paid_refund_amount",
            "source_table": "refunds",
            "amount_column": "amount_cents",
            "status_value": "paid",
            "date_column": "created_at",
            "period_table": "orders",
            "period_date_column": "created_at",
        }
    )
    catalog["default_metric_versions"] = {"paid_refund_amount": "1.0.0"}

    query = _compile_metric_sql(
        catalog,
        "paid_refund_amount",
        "2026-04-01",
        "2026-07-01",
        dialect="sqlite",
        dimension="region",
        role="normal",
    )

    assert "o.tenant_id=f.tenant_id AND o.order_id=f.order_id" in query["sql"]
    assert "r.tenant_id=o.tenant_id AND r.region_id=o.region_id" in query["sql"]


def test_month_metric_returns_registered_month_dimension_alias():
    query = _compile_metric_sql(
        _sales_catalog(),
        "sales_amount",
        "2026-04-01",
        "2026-07-01",
        dialect="sqlite",
        dimension="month",
        role="normal",
    )

    assert "strftime('%Y-%m', o.created_at) AS period" in query["sql"]
    assert "metric_0.period AS month" in query["sql"]


def _south_china_metric_catalog():
    catalog = _sales_catalog()
    catalog["catalog_version"] = "1.2.0"
    catalog["dimensions"]["area"] = {
        "table": "regions",
        "column": "area",
        "join_column": "region_id",
        "allowed_values": ["South China"],
    }
    catalog["metrics"].extend(
        [
            {
                "id": "paid_refund_amount",
                "version": "1.0.0",
                "status": "published",
                "calculation": "sum",
                "source_table": "refunds",
                "amount_column": "amount_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "paid",
                "period_table": "refunds",
                "period_date_column": "created_at",
            },
            {
                "id": "refund_rate",
                "version": "1.0.0",
                "status": "published",
                "calculation": "percentage_ratio",
                "dependencies": ["paid_refund_amount", "sales_amount"],
                "dependency_versions": {
                    "paid_refund_amount": "1.0.0",
                    "sales_amount": "1.0.0",
                },
                "precision": 2,
            },
        ]
    )
    catalog["default_metric_versions"].update(
        {"paid_refund_amount": "1.0.0", "refund_rate": "1.0.0"}
    )
    return catalog


def test_area_scoped_metric_bundle_returns_one_combined_result(monkeypatch):
    from dbgpt_app.openapi.api_v1.tools import metric_query as metric_query_module

    catalog = _south_china_metric_catalog()
    monkeypatch.setattr(
        metric_query_module,
        "load_database_metric_catalog",
        lambda *_args, **_kwargs: catalog,
    )
    executed_sql = []

    def execute_query(*, sql):
        executed_sql.append(sql)
        if "sales_cents" in sql:
            columns, rows = ["sales_cents"], [[77000]]
        else:
            columns, rows = ["refund_rate_pct"], [[6.1]]
        return json.dumps(
            {
                "result": {
                    "type": "sql_result",
                    "columns": columns,
                    "rows": rows,
                    "row_count": 1,
                    "truncated": False,
                }
            }
        )

    metric_tool = make_metric_query(
        {"data_source_id": "ecommerce-demo", "role": "normal"},
        sqlite3.connect(":memory:"),
        execute_query,
    )
    result = json.loads(
        metric_tool(
            metric_ids=["sales_amount", "refund_rate"],
            start_date="2026-04-01",
            end_date="2026-07-01",
            region_area="South China",
        )
    )

    assert result["result"]["columns"] == ["sales_cents", "refund_rate_pct"]
    assert result["result"]["rows"] == [[77000, 6.1]]
    assert len(executed_sql) == 2
    assert all("r.area = 'South China'" in sql for sql in executed_sql)


def test_area_scope_rejects_values_outside_server_catalog():
    catalog = _south_china_metric_catalog()

    with pytest.raises(ValueError, match="未发布该区域范围"):
        _compile_metric_sql(
            catalog,
            "sales_amount",
            "2026-04-01",
            "2026-07-01",
            dialect="sqlite",
            region_area="North China",
            role="normal",
        )
