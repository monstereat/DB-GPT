"""Versioned metric definitions compiled to allowlisted read-only SQL."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from ecommerce_demo import _TABLE_COLUMNS, _TABLES

_SCHEMA_COLUMNS = {
    table_name: {column["name"] for column in table["columns"]}
    for table_name, table in _TABLES.items()
}

_CATALOG = json.loads(
    Path(__file__).with_name("metric_catalog.json").read_text(encoding="utf-8")
)
_METRICS: dict[str, dict[str, dict[str, Any]]] = {}
for _metric in _CATALOG["metrics"]:
    _METRICS.setdefault(_metric["id"], {})[_metric["version"]] = _metric
_DEFAULT_METRIC_VERSIONS = _CATALOG.get("default_metric_versions", {})
_OUTPUT_COLUMNS = {
    "sales_amount": "sales_cents",
    "paid_refund_amount": "refunded_cents",
    "net_sales_amount": "net_sales_cents",
    "refund_rate": "refund_rate_pct",
    "gross_margin_rate": "gross_margin_rate_pct",
}


def _catalog_parts(catalog: dict[str, Any] | None = None):
    if catalog is None:
        return _CATALOG, _METRICS, _DEFAULT_METRIC_VERSIONS
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for metric in catalog["metrics"]:
        metrics.setdefault(metric["id"], {})[metric["version"]] = metric
    return catalog, metrics, catalog.get("default_metric_versions", {})


def validate_metric_catalog(catalog: dict[str, Any]) -> None:
    """Validate a candidate catalog against the fixed demo schema/compiler."""
    _validate_catalog(catalog)


def _validate_catalog(catalog: dict[str, Any] | None = None) -> None:
    catalog, metrics, default_versions = _catalog_parts(catalog)
    seen_versions = set()
    for metric in catalog["metrics"]:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", metric["id"]):
            raise ValueError("Metric catalog contains an invalid metric ID")
        if metric["id"] not in _OUTPUT_COLUMNS:
            raise ValueError("Metric ID has no registered compiler output")
        version_key = (metric["id"], metric.get("version"))
        if version_key in seen_versions:
            raise ValueError("Metric catalog contains a duplicate metric version")
        seen_versions.add(version_key)
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(metric.get("version", ""))):
            raise ValueError("Metric versions must use semantic version numbers")
        if metric.get("status", "published") not in {"published", "draft", "retired"}:
            raise ValueError("Metric version has an unsupported publication status")
        if not metric.get("definition"):
            raise ValueError("Every metric version needs a business definition")
        calculation = metric.get("calculation")
        if calculation == "sum":
            table = metric.get("source_table")
            columns = _TABLE_COLUMNS.get(table, set())
            period_table = metric.get("period_table", table)
            period_date_column = metric.get(
                "period_date_column", metric.get("date_column")
            )
            if (
                not {
                    metric.get("amount_column"),
                    metric.get("status_column"),
                }
                <= columns
            ):
                raise ValueError("Metric source fields must be Agent-queryable")
            if period_date_column not in _TABLE_COLUMNS.get(period_table, set()):
                raise ValueError("Metric period field must be Agent-queryable")
            if period_table not in {table, "orders"}:
                raise ValueError("Metric period table is not supported")
            if table == "refunds" and period_table == "orders":
                if "order_id" not in columns:
                    raise ValueError("Order-cohort refunds require order keys")
            if metric.get("source_table") not in {"orders", "refunds"}:
                raise ValueError("Metric source table is not supported")
        elif calculation == "gross_margin_rate":
            product_columns = {
                column["name"]: column for column in _TABLES["products"]["columns"]
            }
            if (
                metric["id"] != "gross_margin_rate"
                or metric.get("allowed_roles") != ["admin"]
                or not isinstance(metric.get("precision"), int)
                or not 0 <= metric["precision"] <= 6
                or product_columns.get("internal_cost_cents", {}).get("classification")
                != "confidential"
                or product_columns["internal_cost_cents"].get("agent_queryable")
                is not False
                or not {
                    "order_id",
                    "created_at",
                    "status",
                    "tenant_id",
                }
                <= _SCHEMA_COLUMNS["orders"]
                or not {
                    "order_id",
                    "product_id",
                    "quantity",
                    "unit_price_cents",
                    "tenant_id",
                }
                <= _SCHEMA_COLUMNS["order_items"]
            ):
                raise ValueError("Invalid restricted gross margin definition")
        elif calculation in {"subtract", "percentage_ratio"}:
            dependencies = metric.get("dependencies", [])
            if len(dependencies) != 2 or any(
                dep not in metrics for dep in dependencies
            ):
                raise ValueError("Derived metrics require two registered dependencies")
            dependency_versions = metric.get("dependency_versions", {})
            if set(dependency_versions) != set(dependencies):
                raise ValueError("Derived metrics must pin every dependency version")
            if any(
                dependency_versions[dep] not in metrics[dep] for dep in dependencies
            ):
                raise ValueError(
                    "Derived metrics reference an unknown dependency version"
                )
            if any(
                metrics[dep][dependency_versions[dep]].get("status", "published")
                != "published"
                for dep in dependencies
            ):
                raise ValueError(
                    "Published metrics cannot depend on unpublished versions"
                )
        else:
            raise ValueError("Metric calculation is not supported")

    if set(default_versions) != set(metrics):
        raise ValueError("Every metric needs exactly one default published version")
    for metric_id, version in default_versions.items():
        metric = metrics[metric_id].get(version)
        if not metric or metric.get("status", "published") != "published":
            raise ValueError(
                "Default metric versions must reference a published release"
            )

    region = _CATALOG.get("dimensions", {}).get("region", {})
    if region.get("table") != "regions" or region.get(
        "column"
    ) not in _TABLE_COLUMNS.get("regions", set()):
        raise ValueError("Region dimension must reference a queryable schema field")

    _validate_dependency_graph(metrics)


def _validate_dependency_graph(
    metrics: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> None:
    """Reject cyclic references between pinned metric versions."""
    graph = metrics or _METRICS
    states: dict[tuple[str, str], int] = {}

    def visit(key: tuple[str, str]) -> None:
        state = states.get(key, 0)
        if state == 1:
            raise ValueError("Metric dependency graph contains a cycle")
        if state == 2:
            return
        states[key] = 1
        metric = graph[key[0]][key[1]]
        for dependency in metric.get("dependencies", []):
            dependency_version = metric["dependency_versions"][dependency]
            visit((dependency, dependency_version))
        states[key] = 2

    for metric_id, versions in graph.items():
        for version in versions:
            visit((metric_id, version))


_validate_catalog()


def _resolve_metric(
    metric_id: str,
    version: str | None = None,
    *,
    role: str | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog, metrics, defaults = _catalog_parts(catalog)
    versions = metrics.get(metric_id)
    if versions is None:
        raise ValueError("Unknown metric ID")
    selected_version = version or defaults[metric_id]
    metric = versions.get(selected_version)
    if metric is None or metric.get("status", "published") != "published":
        raise ValueError("Metric version is not published")
    if metric.get("allowed_roles") and role not in metric["allowed_roles"]:
        raise ValueError("Metric is not available to this role")
    return metric


def _date_literal(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Metric date boundaries must use YYYY-MM-DD strings")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            "Metric date boundaries must use YYYY-MM-DD strings"
        ) from error
    if parsed.isoformat() != value:
        raise ValueError("Metric date boundaries must use YYYY-MM-DD strings")
    return f"'{value}'"


def _source_aggregate(
    metric: dict[str, Any], start: str, end: str, dimension: str | None
) -> str:
    source_table = metric["source_table"]
    alias = "o" if source_table == "orders" else "f"
    source = f"{source_table} {alias}"
    dimension_join = ""
    dimension_field = ""
    group_clause = ""
    period_table = metric.get("period_table", source_table)
    period_date_column = metric.get("period_date_column", metric["date_column"])
    needs_order_join = source_table == "refunds" and (
        period_table == "orders" or dimension == "region"
    )
    if needs_order_join:
        source += " JOIN orders o ON o.order_id=f.order_id"
    if dimension == "region":
        dimension_source_alias = alias if source_table == "orders" else "o"
        dimension_join = (
            f" JOIN regions r ON r.region_id={dimension_source_alias}.region_id"
        )
        dimension_field = "r.name AS region, "
        group_clause = " GROUP BY r.name"
    elif dimension == "month":
        period_alias = "o" if period_table == "orders" else alias
        month_expression = f"strftime('%Y-%m', {period_alias}.{period_date_column})"
        dimension_field = f"{month_expression} AS period, "
        group_clause = f" GROUP BY {month_expression}"

    amount = metric["amount_column"]
    period_alias = "o" if period_table == "orders" else alias
    status_column = metric["status_column"]
    status_value = metric["status_value"].replace("'", "''")
    start_sql, end_sql = _date_literal(start), _date_literal(end)
    return (
        f"SELECT {dimension_field}SUM({alias}.{amount}) AS amount "
        f"FROM {source}{dimension_join} "
        f"WHERE {period_alias}.{period_date_column} >= {start_sql} "
        f"AND {period_alias}.{period_date_column} < {end_sql} "
        f"AND {alias}.{status_column} = '{status_value}'{group_clause}"
    )


def _compile_metric_ctes(
    metric_key: tuple[str, str],
    start_date: str,
    end_date: str,
    dimension: str | None,
    role: str | None,
    catalog: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """Compile a pinned metric dependency graph into ordered SQL CTEs."""
    ctes: list[str] = []
    aliases: dict[tuple[str, str], str] = {}

    def compile_metric(key: tuple[str, str]) -> str:
        if key in aliases:
            return aliases[key]

        metric_id, version = key
        metric = _resolve_metric(metric_id, version, role=role, catalog=catalog)
        calculation = metric["calculation"]
        alias = f"metric_{len(aliases)}"
        aliases[key] = alias

        if calculation == "sum":
            sql = _source_aggregate(metric, start_date, end_date, dimension)
        elif calculation == "gross_margin_rate":
            precision = metric["precision"]
            source = (
                "orders o JOIN order_items oi ON oi.order_id=o.order_id "
                "JOIN products p ON p.product_id=oi.product_id"
            )
            dimension_join = ""
            dimension_field = ""
            group_clause = ""
            if dimension == "region":
                dimension_join = " JOIN regions r ON r.region_id=o.region_id"
                dimension_field = "r.name AS region, "
                group_clause = " GROUP BY r.name"
            elif dimension == "month":
                month = "strftime('%Y-%m', o.created_at)"
                dimension_field = f"{month} AS period, "
                group_clause = f" GROUP BY {month}"
            sales = "SUM(oi.quantity*oi.unit_price_cents)"
            cost = "SUM(oi.quantity*p.internal_cost_cents)"
            start_sql, end_sql = _date_literal(start_date), _date_literal(end_date)
            sql = (
                f"SELECT {dimension_field}CASE WHEN {sales}=0 THEN NULL ELSE "
                f"ROUND(100.0*({sales}-{cost})/{sales}, {precision}) "
                f"END AS amount FROM {source}{dimension_join} "
                f"WHERE o.created_at >= {start_sql} AND o.created_at < {end_sql} "
                f"AND o.status = 'completed'{group_clause}"
            )
        else:
            dependencies = metric["dependencies"]
            dependency_versions = metric["dependency_versions"]
            dependency_keys = [
                (dependency, dependency_versions[dependency])
                for dependency in dependencies
            ]
            dependency_aliases = [
                compile_metric(dependency_key) for dependency_key in dependency_keys
            ]
            references = [
                f"{dep_alias} AS d{index}"
                for index, dep_alias in enumerate(dependency_aliases)
            ]
            if dimension is None:
                joins = " CROSS JOIN ".join(references)
                dimension_select = ""
            else:
                dimension_column = "period" if dimension == "month" else "region"
                anchor_index = 1 if calculation == "percentage_ratio" else 0
                joins = references[anchor_index]
                joins += "".join(
                    f" LEFT JOIN {reference} ON d{anchor_index}.{dimension_column}="
                    f"d{index}.{dimension_column}"
                    for index, reference in enumerate(references)
                    if index != anchor_index
                )
                dimension_select = (
                    f"d{anchor_index}.{dimension_column} AS {dimension_column}, "
                )

            if calculation == "subtract":
                formula = "d0.amount-COALESCE(d1.amount, 0)"
            elif calculation == "percentage_ratio":
                formula = (
                    "CASE WHEN d1.amount=0 THEN NULL ELSE "
                    f"ROUND(100.0*COALESCE(d0.amount, 0)/d1.amount, "
                    f"{metric['precision']}) END"
                )
            else:  # Catalog validation should make this unreachable.
                raise ValueError("Metric calculation is not supported")
            sql = f"SELECT {dimension_select}{formula} AS amount FROM {joins}"

        ctes.append(f"{alias} AS ({sql})")
        return alias

    root_alias = compile_metric(metric_key)
    return ctes, root_alias


def build_metric_query(
    metric_id: str,
    start_date: str,
    end_date: str,
    *,
    dimension: str | None = None,
    metric_version: str | None = None,
    role: str | None = None,
    metric_catalog: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Build a SQL query and return the exact metric definition metadata.

    Dates are parsed as canonical ISO dates; metrics, schema identifiers and
    dimensions come only from the server-owned catalog and Schema metadata.
    """
    if dimension not in {None, "region", "month"}:
        raise ValueError("Unsupported metric dimension")
    _date_literal(start_date)
    _date_literal(end_date)
    if date.fromisoformat(start_date) >= date.fromisoformat(end_date):
        raise ValueError("Metric start date must be earlier than end date")

    if metric_catalog is not None:
        _validate_catalog(metric_catalog)
    metric = _resolve_metric(
        metric_id, metric_version, role=role, catalog=metric_catalog
    )
    output_column = _OUTPUT_COLUMNS[metric_id]
    ctes, root_alias = _compile_metric_ctes(
        (metric_id, metric["version"]),
        start_date,
        end_date,
        dimension,
        role,
        metric_catalog,
    )
    select_columns = []
    if dimension is not None:
        dimension_column = "period" if dimension == "month" else "region"
        select_columns.append(f"{root_alias}.{dimension_column} AS {dimension_column}")
    select_columns.append(f"{root_alias}.amount AS {output_column}")
    sql = f"WITH {', '.join(ctes)} SELECT {', '.join(select_columns)} FROM {root_alias}"
    if dimension is not None:
        sql += f" ORDER BY {dimension_column}"

    result = {
        "sql": sql,
        "metric_id": metric_id,
        "metric_version": metric["version"],
        "catalog_version": (metric_catalog or _CATALOG)["catalog_version"],
        "definition": metric["definition"],
        "unit": metric["unit"],
        "start_date": start_date,
        "end_date": end_date,
        "dimension": dimension or "",
    }
    content_hashes = (metric_catalog or {}).get("metric_content_sha256", {})
    if f"{metric_id}@{metric['version']}" in content_hashes:
        result["content_sha256"] = content_hashes[f"{metric_id}@{metric['version']}"]
    return result
