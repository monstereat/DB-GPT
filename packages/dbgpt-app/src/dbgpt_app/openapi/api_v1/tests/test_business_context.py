import json
import sqlite3

import pytest

from dbgpt_app.openapi.api_v1.business_context import (
    apply_database_row_scope,
    authorize_agent_datasource_access,
    filter_metric_catalog_for_role,
    format_database_business_context,
    load_database_business_context,
    load_database_metric_catalog,
    load_database_schema_policy,
    prepare_agent_database_query,
    prepare_database_query,
    validate_query_columns,
)


def test_loads_only_context_mapped_to_selected_datasource(tmp_path):
    context_file = tmp_path / "business.md"
    context_file.write_text("销售额按已完成订单统计。", encoding="utf-8")
    mapping = json.dumps({"sales-db": str(context_file), "other-db": "missing.md"})

    assert load_database_business_context("sales-db", mapping_json=mapping) == (
        "销售额按已完成订单统计。"
    )
    assert load_database_business_context("unmapped-db", mapping_json=mapping) is None


def test_invalid_or_oversized_context_fails_closed(tmp_path):
    oversized_file = tmp_path / "large.md"
    oversized_file.write_text("x" * (33 * 1024), encoding="utf-8")

    assert load_database_business_context("sales-db", mapping_json="not-json") is None
    assert (
        load_database_business_context(
            "sales-db", mapping_json=json.dumps({"sales-db": str(oversized_file)})
        )
        is None
    )


def test_formats_business_context_as_reference_data():
    prompt_context = format_database_business_context(
        "利润率定义：净销售额减成本后除以净销售额。"
    )

    assert "<business_context>" in prompt_context
    assert "数据库 Schema 和服务端授权策略优先" in prompt_context
    assert "利润率定义" in prompt_context
    assert format_database_business_context(None) == ""


def test_schema_policy_blocks_sensitive_fields_but_allows_safe_aggregates(tmp_path):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id"},
                "tables": [
                    {
                        "name": "products",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "product_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                            {
                                "name": "internal_cost_cents",
                                "classification": "confidential",
                                "agent_queryable": False,
                            },
                        ],
                    },
                    {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "order_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                        ],
                    },
                    {
                        "name": "product_cost_view",
                        "type": "view",
                        "definition": "SELECT product_id FROM products",
                        "columns": [
                            {
                                "name": "product_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    mapping = json.dumps({"sales-db": str(schema_file)})
    policy = load_database_schema_policy("sales-db", mapping_json=mapping)
    assert policy["views"] == {"product_cost_view"}

    with pytest.raises(ValueError, match="敏感字段"):
        validate_query_columns(
            "SELECT p.internal_cost_cents FROM products p",
            policy,
            dialect="sqlite",
        )
    for sql in (
        "WITH costs AS (SELECT internal_cost_cents AS value FROM products) "
        "SELECT value FROM costs",
        "SELECT (SELECT MAX(internal_cost_cents) FROM products) AS cost",
        "SELECT p.* FROM products p",
    ):
        with pytest.raises(ValueError):
            validate_query_columns(sql, policy, dialect="sqlite")
    with pytest.raises(ValueError, match="通配符"):
        validate_query_columns("SELECT * FROM products", policy, dialect="sqlite")
    with pytest.raises(ValueError, match="未登记的数据表或视图"):
        validate_query_columns(
            "SELECT hidden_cost FROM other_cost_view", policy, dialect="sqlite"
        )
    validate_query_columns(
        "SELECT product_id FROM product_cost_view", policy, dialect="sqlite"
    )
    with pytest.raises(ValueError, match="租户隔离字段"):
        validate_query_columns(
            "SELECT tenant_id FROM products", policy, dialect="sqlite"
        )
    validate_query_columns("SELECT COUNT(*) FROM products", policy, dialect="sqlite")
    validate_query_columns(
        "SELECT p.product_id FROM products p JOIN orders o "
        "ON p.tenant_id = o.tenant_id",
        policy,
        dialect="sqlite",
    )


def test_registered_projection_view_expands_before_tenant_row_scope(
    tmp_path, monkeypatch
):
    from dbgpt_app.openapi.api_v1 import business_context

    schema_file = tmp_path / "view-schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id"},
                "tables": [
                    {
                        "name": "products",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "product_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                            {
                                "name": "internal_cost_cents",
                                "classification": "confidential",
                                "agent_queryable": False,
                            },
                        ],
                    },
                    {
                        "name": "public_products",
                        "type": "view",
                        "definition": "SELECT product_id FROM products",
                        "columns": [
                            {
                                "name": "product_id",
                                "classification": "business",
                                "agent_queryable": True,
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = load_database_schema_policy(
        "sales-db", mapping_json=json.dumps({"sales-db": str(schema_file)})
    )
    monkeypatch.setattr(
        business_context, "load_database_schema_policy", lambda _database_id: policy
    )
    scoped, audit_context = prepare_database_query(
        "SELECT pp.product_id FROM public_products pp",
        {
            "data_source_id": "sales-db",
            "tenant_id": "tenant-a",
            "role": "admin",
            "authorization_policy_version": "datasource-v1",
        },
        type("Connector", (), {"dialect": "sqlite"})(),
    )
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE products (tenant_id TEXT, product_id TEXT, "
        "internal_cost_cents INTEGER)"
    )
    connection.executemany(
        "INSERT INTO products VALUES (?, ?, ?)",
        [("tenant-a", "visible", 50), ("tenant-b", "hidden", 10)],
    )
    assert connection.execute(scoped).fetchall() == [("visible",)]
    assert "internal_cost_cents" not in scoped
    assert (
        f"views-{policy['view_policy_hash'][:12]}"
        in audit_context["authorization_policy_version"]
    )


@pytest.mark.parametrize(
    "definition, expected_message",
    [
        (None, "缺少受审计定义"),
        ("SELECT internal_cost_cents FROM products", "受限或重复字段"),
        ("SELECT product_id FROM missing_table", "未登记或不支持的对象"),
        (
            "SELECT product_id FROM products WHERE product_id IS NOT NULL",
            "安全投影规则",
        ),
        ("SELECT product_id AS other_id FROM products", "登记列不一致"),
        (
            "SELECT product_id FROM products; SELECT product_id FROM products",
            "单条 SELECT",
        ),
    ],
)
def test_registered_view_with_unreviewed_definition_fails_closed(
    tmp_path, definition, expected_message
):
    from dbgpt_app.openapi.api_v1.business_context import expand_registered_views

    policy = {
        "views": {"public_products"},
        "view_definitions": {"public_products": definition} if definition else {},
        "tables": {
            "products": {"tenant_id", "product_id", "internal_cost_cents"},
            "public_products": {"product_id"},
        },
        "queryable_columns": {"products": {"product_id"}},
        "column_classifications": {
            "products": {
                "tenant_id": "tenant_key",
                "product_id": "business",
                "internal_cost_cents": "confidential",
            }
        },
    }
    with pytest.raises(ValueError, match=expected_message):
        expand_registered_views(
            "SELECT product_id FROM public_products", policy, dialect="sqlite"
        )


@pytest.mark.parametrize(
    "react_state",
    [
        {"tenant_id": None, "verified_execution_context": {"actor_id": "u1"}},
        {"tenant_id": None, "actor_user_id": "legacy-user", "role": "admin"},
    ],
)
def test_missing_schema_policy_fails_closed_for_authenticated_context(
    monkeypatch, react_state
):
    from dbgpt_app.openapi.api_v1 import business_context

    monkeypatch.setattr(
        business_context, "load_database_schema_policy", lambda _database_id: None
    )
    with pytest.raises(ValueError, match="未配置租户过滤策略"):
        prepare_database_query(
            "SELECT order_id FROM orders",
            {"data_source_id": "sales-db", **react_state},
            type("Connector", (), {"dialect": "sqlite"})(),
        )


def test_missing_schema_policy_preserves_anonymous_local_query(monkeypatch):
    from dbgpt_app.openapi.api_v1 import business_context

    monkeypatch.setattr(
        business_context, "load_database_schema_policy", lambda _database_id: None
    )
    sql, state = prepare_database_query(
        "SELECT order_id FROM orders",
        {"data_source_id": "sales-db"},
        type("Connector", (), {"dialect": "sqlite"})(),
    )

    assert sql == "SELECT order_id FROM orders"
    assert state["data_source_id"] == "sales-db"


def test_invalid_mapped_schema_policy_fails_closed(tmp_path):
    mapping = json.dumps({"sales-db": str(tmp_path / "missing.json")})

    with pytest.raises(ValueError, match="unavailable"):
        load_database_schema_policy("sales-db", mapping_json=mapping)

    invalid_schema = tmp_path / "invalid-schema.json"
    invalid_schema.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id"},
                "tables": [
                    {
                        "name": "products",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "internal_cost_cents",
                                "classification": "confidencial",
                                "agent_queryable": False,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid|tenant scope"):
        load_database_schema_policy(
            "sales-db",
            mapping_json=json.dumps({"sales-db": str(invalid_schema)}),
        )


def test_schema_row_scope_filters_tenant_and_sales_region_across_related_tables(
    tmp_path,
):
    def column(name, classification="business", agent_queryable=True):
        return {
            "name": name,
            "classification": classification,
            "agent_queryable": agent_queryable,
        }

    schema_file = tmp_path / "row-scope-schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {
                    "tenant_column": "tenant_id",
                    "policy_version": "scope-v1",
                    "region_scope": {
                        "direct": {"orders": "region_id"},
                        "via_orders": {
                            "order_items": "order_id",
                            "refunds": "order_id",
                        },
                        "via_order_items": {"products": "product_id"},
                    },
                },
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            column("tenant_id", "tenant_key", False),
                            column("order_id"),
                            column("region_id"),
                        ],
                    },
                    {
                        "name": "order_items",
                        "columns": [
                            column("tenant_id", "tenant_key", False),
                            column("item_id"),
                            column("order_id"),
                            column("product_id"),
                        ],
                    },
                    {
                        "name": "refunds",
                        "columns": [
                            column("tenant_id", "tenant_key", False),
                            column("refund_id"),
                            column("order_id"),
                        ],
                    },
                    {
                        "name": "products",
                        "columns": [
                            column("tenant_id", "tenant_key", False),
                            column("product_id"),
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = load_database_schema_policy(
        "sales-db", mapping_json=json.dumps({"sales-db": str(schema_file)})
    )
    database = tmp_path / "row-scope.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE orders (tenant_id TEXT, order_id INTEGER, region_id TEXT);
            CREATE TABLE order_items (
                tenant_id TEXT, item_id INTEGER, order_id INTEGER, product_id TEXT
            );
            CREATE TABLE refunds (tenant_id TEXT, refund_id INTEGER, order_id INTEGER);
            CREATE TABLE products (tenant_id TEXT, product_id TEXT);
            INSERT INTO orders VALUES
                ('tenant-a', 1, 'a-gz'), ('tenant-a', 2, 'a-sz'),
                ('tenant-b', 3, 'b-gz');
            INSERT INTO order_items VALUES
                ('tenant-a', 1, 1, 'shared'), ('tenant-a', 2, 2, 'shared'),
                ('tenant-a', 3, 2, 'sz-only'), ('tenant-b', 4, 3, 'shared');
            INSERT INTO refunds VALUES
                ('tenant-a', 11, 1), ('tenant-a', 12, 2), ('tenant-b', 13, 3);
            INSERT INTO products VALUES
                ('tenant-a', 'shared'), ('tenant-a', 'sz-only'),
                ('tenant-b', 'shared');
            """
        )

        queries = {
            "orders": ("SELECT order_id FROM orders ORDER BY order_id", [(1,)]),
            "order_items": ("SELECT item_id FROM order_items ORDER BY item_id", [(1,)]),
            "refunds": ("SELECT refund_id FROM refunds ORDER BY refund_id", [(11,)]),
            "products": (
                "SELECT product_id FROM products ORDER BY product_id",
                [("shared",)],
            ),
        }
        for sql, expected in queries.values():
            scoped_sql = apply_database_row_scope(
                sql,
                policy,
                tenant_id="tenant-a",
                role="sales",
                region_id="a-gz",
                dialect="sqlite",
            )
            assert connection.execute(scoped_sql).fetchall() == expected

        cte_sql = apply_database_row_scope(
            "WITH rows AS (SELECT order_id FROM orders) SELECT order_id FROM rows",
            policy,
            tenant_id="tenant-a",
            role="normal",
            region_id=None,
            dialect="sqlite",
        )
        assert connection.execute(cte_sql).fetchall() == [(1,), (2,)]

        nested_cte_sql = apply_database_row_scope(
            "WITH eligible AS (SELECT order_id FROM orders), "
            "matched AS (SELECT e.order_id FROM eligible e WHERE EXISTS ("
            "SELECT 1 FROM orders o WHERE o.order_id = e.order_id)) "
            "SELECT order_id FROM matched ORDER BY order_id",
            policy,
            tenant_id="tenant-a",
            role="normal",
            region_id=None,
            dialect="sqlite",
        )
        assert connection.execute(nested_cte_sql).fetchall() == [(1,), (2,)]

        union_sql = apply_database_row_scope(
            "SELECT order_id FROM orders WHERE order_id = 1 UNION ALL "
            "SELECT order_id FROM orders WHERE order_id = 3",
            policy,
            tenant_id="tenant-a",
            role="normal",
            region_id=None,
            dialect="sqlite",
        )
        assert connection.execute(union_sql).fetchall() == [(1,)]

        with pytest.raises(ValueError, match="未登记或未受租户保护的表"):
            apply_database_row_scope(
                "SELECT value FROM json_each('[1, 2]')",
                policy,
                tenant_id="tenant-a",
                role="normal",
                region_id=None,
                dialect="sqlite",
            )

        with pytest.raises(ValueError, match="租户范围"):
            apply_database_row_scope(
                "SELECT order_id FROM orders",
                policy,
                tenant_id=None,
                role="normal",
                region_id=None,
                dialect="sqlite",
            )
        with pytest.raises(ValueError, match="区域范围"):
            apply_database_row_scope(
                "SELECT order_id FROM orders",
                policy,
                tenant_id="tenant-a",
                role="sales",
                region_id=None,
                dialect="sqlite",
            )
        with pytest.raises(ValueError, match="未登记的数据库或 Schema"):
            apply_database_row_scope(
                "SELECT order_id FROM other_schema.orders",
                policy,
                tenant_id="tenant-a",
                role="normal",
                region_id=None,
                dialect="sqlite",
            )
        with pytest.raises(ValueError, match="未登记"):
            apply_database_row_scope(
                "SELECT name FROM sqlite_master",
                policy,
                tenant_id="tenant-a",
                role="normal",
                region_id=None,
                dialect="sqlite",
            )


def test_loads_metric_catalog_only_for_mapped_datasource(tmp_path):
    catalog_file = tmp_path / "metrics.json"
    catalog_file.write_text(
        json.dumps(
            {
                "catalog_version": "1.2.0",
                "default_metric_versions": {"sales_amount": "1.0.0"},
                "metrics": [
                    {
                        "id": "sales_amount",
                        "version": "1.0.0",
                        "name": "销售额",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "统计已完成订单金额。",
                        "source_table": "orders",
                        "amount_column": "total_cents",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    mapping = json.dumps({"sales-db": str(catalog_file)})

    catalog = load_database_metric_catalog("sales-db", mapping_json=mapping)

    assert catalog["catalog_version"] == "1.2.0"
    assert catalog["metrics"] == [
        {
            "id": "sales_amount",
            "version": "1.0.0",
            "name": "销售额",
            "calculation": "sum",
            "unit": "CNY_cent",
            "definition": "统计已完成订单金额。",
            "dependencies": [],
            "dependency_versions": {},
        }
    ]
    assert load_database_metric_catalog("unmapped-db", mapping_json=mapping) is None


def test_invalid_metric_catalog_fails_closed(tmp_path):
    catalog_file = tmp_path / "invalid.json"
    catalog_file.write_text(
        '{"catalog_version":"1.0.0","metrics":[{}]}', encoding="utf-8"
    )
    mapping = json.dumps({"sales-db": str(catalog_file)})

    assert load_database_metric_catalog("sales-db", mapping_json=mapping) is None
    assert load_database_metric_catalog("sales-db", mapping_json="invalid") is None


def _dependency_catalog():
    return {
        "catalog_version": "1.0.0",
        "default_metric_versions": {
            "sales_amount": "1.0.0",
            "refund_amount": "1.0.0",
            "net_sales": "1.0.0",
        },
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "name": "销售额",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "销售额定义",
            },
            {
                "id": "refund_amount",
                "version": "1.0.0",
                "name": "退款额",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "退款额定义",
            },
            {
                "id": "net_sales",
                "version": "1.0.0",
                "name": "净销售额",
                "calculation": "subtract",
                "unit": "CNY_cent",
                "definition": "净销售额定义",
                "dependencies": ["sales_amount", "refund_amount"],
                "dependency_versions": {
                    "sales_amount": "1.0.0",
                    "refund_amount": "1.0.0",
                },
            },
        ],
    }


def test_metric_catalog_accepts_unique_versions_with_resolved_dependency_pins(
    tmp_path,
):
    catalog_file = tmp_path / "valid-dependencies.json"
    catalog_file.write_text(json.dumps(_dependency_catalog()), encoding="utf-8")
    mapping = json.dumps({"sales-db": str(catalog_file)})

    loaded = load_database_metric_catalog("sales-db", mapping_json=mapping)

    assert loaded is not None
    assert loaded["metrics"][-1]["dependency_versions"] == {
        "sales_amount": "1.0.0",
        "refund_amount": "1.0.0",
    }


@pytest.mark.parametrize(
    "invalid_change",
    [
        "duplicate_version",
        "missing_pin",
        "dangling_dependency",
        "unknown_pin",
        "unknown_default",
        "draft_default",
        "dependency_cycle",
    ],
)
def test_metric_catalog_rejects_ambiguous_versions_and_dependencies(
    tmp_path, invalid_change
):
    catalog = _dependency_catalog()
    if invalid_change == "duplicate_version":
        catalog["metrics"].append(dict(catalog["metrics"][0]))
    elif invalid_change == "missing_pin":
        catalog["metrics"][-1]["dependency_versions"].pop("refund_amount")
    elif invalid_change == "dangling_dependency":
        catalog["metrics"][-1]["dependencies"].append("missing_metric")
        catalog["metrics"][-1]["dependency_versions"]["missing_metric"] = "1.0.0"
    elif invalid_change == "unknown_pin":
        catalog["metrics"][-1]["dependency_versions"]["refund_amount"] = "9.9.9"
    elif invalid_change == "unknown_default":
        catalog["default_metric_versions"]["net_sales"] = "9.9.9"
    elif invalid_change == "draft_default":
        catalog["metrics"][0]["status"] = "draft"
    elif invalid_change == "dependency_cycle":
        catalog["metrics"][0]["dependencies"] = ["net_sales"]
        catalog["metrics"][0]["dependency_versions"] = {"net_sales": "1.0.0"}

    catalog_file = tmp_path / "invalid-dependencies.json"
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    mapping = json.dumps({"sales-db": str(catalog_file)})

    assert load_database_metric_catalog("sales-db", mapping_json=mapping) is None


def test_metric_role_policy_is_validated_and_filters_catalog_defaults(tmp_path):
    catalog_file = tmp_path / "role-metrics.json"
    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {
            "sales_amount": "1.0.0",
            "internal_margin": "1.0.0",
        },
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "name": "销售额",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "销售额定义",
            },
            {
                "id": "internal_margin",
                "version": "1.0.0",
                "name": "毛利率",
                "calculation": "sum",
                "unit": "percent",
                "definition": "内部毛利率定义",
                "allowed_roles": ["admin"],
            },
        ],
    }
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    mapping = json.dumps({"sales-db": str(catalog_file)})

    loaded = load_database_metric_catalog("sales-db", mapping_json=mapping)
    assert loaded["metrics"][1]["allowed_roles"] == ["admin"]

    for role, expected_ids in (
        ("normal", ["sales_amount"]),
        ("admin", ["sales_amount", "internal_margin"]),
    ):
        visible = filter_metric_catalog_for_role(loaded, role)
        assert [metric["id"] for metric in visible["metrics"]] == expected_ids
        assert set(visible["default_metric_versions"]) == set(expected_ids)

    catalog["metrics"][1]["allowed_roles"] = []
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    assert load_database_metric_catalog("sales-db", mapping_json=mapping) is None


def test_public_metric_cannot_depend_on_role_restricted_metric(tmp_path):
    catalog_file = tmp_path / "unsafe-role-dependency.json"
    catalog_file.write_text(
        json.dumps(
            {
                "catalog_version": "1.0.0",
                "default_metric_versions": {
                    "internal_cost": "1.0.0",
                    "public_ratio": "1.0.0",
                },
                "metrics": [
                    {
                        "id": "internal_cost",
                        "version": "1.0.0",
                        "name": "成本",
                        "calculation": "sum",
                        "unit": "CNY_cent",
                        "definition": "内部成本",
                        "allowed_roles": ["admin"],
                    },
                    {
                        "id": "public_ratio",
                        "version": "1.0.0",
                        "name": "公开派生指标",
                        "calculation": "percentage_ratio",
                        "unit": "percent",
                        "definition": "依赖受限成本",
                        "dependencies": ["internal_cost"],
                        "dependency_versions": {
                            "internal_cost": "1.0.0",
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    mapping = json.dumps({"sales-db": str(catalog_file)})

    assert load_database_metric_catalog("sales-db", mapping_json=mapping) is None


def test_compiler_catalog_fields_are_operator_mapped_and_identifier_checked(tmp_path):
    catalog_file = tmp_path / "metrics.json"
    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {"sales_amount": "1.0.0"},
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "name": "销售额",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "已完成订单金额",
                "source_table": "orders",
                "amount_column": "total_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "completed",
            }
        ],
    }
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    mapping = json.dumps({"sales-db": str(catalog_file)})

    compiled = load_database_metric_catalog(
        "sales-db", mapping_json=mapping, include_query_fields=True
    )

    assert compiled["metrics"][0]["source_table"] == "orders"
    assert (
        "source_table"
        not in load_database_metric_catalog("sales-db", mapping_json=mapping)[
            "metrics"
        ][0]
    )

    catalog["metrics"][0]["amount_column"] = "total_cents; DROP TABLE orders"
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    assert (
        load_database_metric_catalog(
            "sales-db", mapping_json=mapping, include_query_fields=True
        )
        is None
    )


def test_metric_catalog_preserves_only_valid_server_area_allowlist(tmp_path):
    catalog_file = tmp_path / "metrics-with-area.json"
    catalog = {
        "catalog_version": "1.0.0",
        "default_metric_versions": {"sales_amount": "1.0.0"},
        "metrics": [
            {
                "id": "sales_amount",
                "version": "1.0.0",
                "name": "销售额",
                "calculation": "sum",
                "unit": "CNY_cent",
                "definition": "已完成订单金额",
                "source_table": "orders",
                "amount_column": "total_cents",
                "date_column": "created_at",
                "status_column": "status",
                "status_value": "completed",
            }
        ],
        "dimensions": {
            "region": {
                "table": "regions",
                "column": "name",
                "join_column": "region_id",
            },
            "area": {
                "table": "regions",
                "column": "area",
                "join_column": "region_id",
                "allowed_values": ["South China"],
            },
        },
    }
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    mapping = json.dumps({"sales-db": str(catalog_file)})

    loaded = load_database_metric_catalog(
        "sales-db", mapping_json=mapping, include_query_fields=True
    )

    assert loaded["dimensions"]["area"] == {
        "table": "regions",
        "column": "area",
        "join_column": "region_id",
        "allowed_values": ["South China"],
    }

    catalog["dimensions"]["area"]["allowed_values"] = ["South China", {}]
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    assert (
        load_database_metric_catalog(
            "sales-db", mapping_json=mapping, include_query_fields=True
        )
        is None
    )


def test_mapped_schema_policy_requires_tenant_scope(tmp_path):
    schema_file = tmp_path / "schema-without-tenant.json"
    schema_file.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "name": "products",
                        "columns": [
                            {
                                "name": "product_id",
                                "classification": "business",
                                "agent_queryable": True,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must define tenant scope"):
        load_database_schema_policy(
            "sales-db", mapping_json=json.dumps({"sales-db": str(schema_file)})
        )


def test_agent_database_query_requires_verified_identity_and_scopes_tenant(
    tmp_path, monkeypatch
):
    schema_file = tmp_path / "schema.json"
    schema_file.write_text(
        json.dumps(
            {
                "source": {"tenant_column": "tenant_id", "policy_version": "1"},
                "tables": [
                    {
                        "name": "orders",
                        "columns": [
                            {
                                "name": "tenant_id",
                                "classification": "tenant_key",
                                "agent_queryable": False,
                            },
                            {
                                "name": "order_id",
                                "classification": "business",
                                "agent_queryable": True,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "DBGPT_DATABASE_SCHEMA_FILES",
        json.dumps({"sales-db": str(schema_file)}),
    )
    identity = {
        "source": "verified_oidc_jwt",
        "actor_id": "alice",
        "role": "normal",
        "tenant_id": "tenant-a",
        "data_source_id": "sales-db",
    }
    connector = type("Connector", (), {"dialect": "sqlite"})()

    with pytest.raises(PermissionError, match="Verified identity"):
        prepare_agent_database_query(
            "SELECT order_id FROM orders",
            {**identity, "source": "request"},
            connector,
        )

    scoped_sql, audit_context = prepare_agent_database_query(
        "SELECT order_id FROM orders", identity, connector
    )

    assert "tenant-a" in scoped_sql
    assert audit_context["actor_id"] == "alice"
    assert "schema-1" in audit_context["authorization_policy_version"]


def test_agent_datasource_access_is_owner_scoped(monkeypatch):
    class _Manager:
        def get_db_list(self, db_name, user_id):
            assert db_name == "sales-db"
            assert user_id == "alice"
            return [{"db_name": "sales-db", "user_id": "alice"}]

    from dbgpt._private.config import Config

    manager = _Manager()
    monkeypatch.setattr(
        Config, "local_db_manager", property(lambda self: manager), raising=False
    )
    identity = {"source": "verified_oidc_jwt", "actor_id": "alice", "role": "normal"}

    authorize_agent_datasource_access("sales-db", identity)

    with pytest.raises(PermissionError, match="Verified identity"):
        authorize_agent_datasource_access("sales-db", {**identity, "source": "request"})
