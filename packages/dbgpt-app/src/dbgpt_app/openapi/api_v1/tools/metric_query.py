"""Compile and execute a published metric through the Agent read-only gateway."""

import json
import logging
import re
import time
from datetime import date
from typing import Any, List, Optional

from dbgpt.agent.resource.tool.base import tool
from dbgpt.util.tracer import SpanType, root_tracer

from ..business_context import (
    filter_metric_catalog_for_role,
    load_database_metric_catalog,
    make_trusted_metric_plan,
    use_trusted_metric_plan,
)

logger = logging.getLogger(__name__)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_METRIC_RESULT_COLUMNS = {
    "sales_amount": "sales_cents",
    "paid_refund_amount": "refunded_cents",
    "net_sales_amount": "net_sales_cents",
    "refund_rate": "refund_rate_pct",
    "gross_margin_rate": "gross_margin_rate_pct",
}


def _quote_date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("日期必须使用 YYYY-MM-DD 格式")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式") from error
    if parsed.isoformat() != value:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式")
    return f"'{value}'"


def _month_expression(dialect: str, alias: str, column: str) -> str:
    field = f"{alias}.{column}"
    if dialect == "sqlite":
        return f"strftime('%Y-%m', {field})"
    if dialect in {"postgres", "postgresql"}:
        return f"TO_CHAR({field}, 'YYYY-MM')"
    if dialect in {"mysql", "mariadb"}:
        return f"DATE_FORMAT({field}, '%Y-%m')"
    raise ValueError("当前数据库方言不支持月度指标维度")


def _compile_metric_sql(
    catalog: dict,
    metric_id: str,
    start_date: str,
    end_date: str,
    *,
    dialect: str,
    dimension: Optional[str] = None,
    metric_version: Optional[str] = None,
    region_area: Optional[str] = None,
    role: Optional[str] = None,
) -> dict[str, str]:
    if dimension not in {None, "region", "month"}:
        raise ValueError("不支持该指标维度")
    start_sql, end_sql = _quote_date(start_date), _quote_date(end_date)
    if date.fromisoformat(start_date) >= date.fromisoformat(end_date):
        raise ValueError("开始日期必须早于结束日期")

    metrics: dict[tuple[str, str], dict[str, Any]] = {}
    for metric in catalog["metrics"]:
        if not _IDENTIFIER.fullmatch(metric["id"]):
            raise ValueError("指标目录包含无效 ID")
        key = (metric["id"], metric["version"])
        if key in metrics:
            raise ValueError("指标目录包含重复版本")
        metrics[key] = metric
    defaults = catalog["default_metric_versions"]
    selected_version = metric_version or defaults.get(metric_id)
    root_key = (metric_id, selected_version or "")
    if root_key not in metrics or metrics[root_key].get("status") != "published":
        raise ValueError("指标或版本未在服务端目录中发布")
    if metrics[root_key].get("allowed_roles") and (
        role not in metrics[root_key]["allowed_roles"]
    ):
        raise ValueError("当前身份无权使用该指标")

    dimensions = catalog.get("dimensions", {})
    if dimension == "region" and "region" not in dimensions:
        raise ValueError("服务端指标目录未发布区域维度")
    area_filter = None
    area_literal = None
    if region_area is not None:
        area_filter = dimensions.get("area")
        region_dimension = dimensions.get("region")
        if (
            not isinstance(region_area, str)
            or not isinstance(area_filter, dict)
            or not isinstance(region_dimension, dict)
            or area_filter.get("table") != region_dimension.get("table")
            or area_filter.get("join_column") != region_dimension.get("join_column")
            or not all(
                isinstance(area_filter.get(key), str)
                and _IDENTIFIER.fullmatch(area_filter[key])
                for key in ("table", "column", "join_column")
            )
            or not isinstance(area_filter.get("allowed_values"), list)
            or region_area not in area_filter["allowed_values"]
        ):
            raise ValueError("指标目录未发布该区域范围")
        area_literal = "'" + region_area.replace("'", "''") + "'"

    ctes: list[str] = []
    aliases: dict[tuple[str, str], str] = {}
    visiting: set[tuple[str, str]] = set()

    def compile_metric(key: tuple[str, str]) -> str:
        if key in visiting:
            raise ValueError("指标依赖图包含循环")
        if key in aliases:
            return aliases[key]
        metric = metrics.get(key)
        if not metric or metric.get("status") != "published":
            raise ValueError("指标依赖的版本未发布")
        if metric.get("allowed_roles") and role not in metric["allowed_roles"]:
            raise ValueError("指标依赖的版本不可供当前身份使用")
        visiting.add(key)
        alias = f"metric_{len(aliases)}"
        aliases[key] = alias
        calculation = metric["calculation"]

        if calculation == "sum":
            source_table = metric["source_table"]
            if source_table not in {"orders", "refunds"}:
                raise ValueError("指标目录包含不支持的来源表")
            for field in (
                "amount_column",
                "date_column",
                "status_column",
                "period_table",
                "period_date_column",
            ):
                if not _IDENTIFIER.fullmatch(metric[field]):
                    raise ValueError("指标目录包含无效字段名")
            if metric["period_table"] not in {"orders", "refunds"}:
                raise ValueError("指标目录包含不支持的时间来源表")
            if metric["period_table"] != source_table and not (
                source_table == "refunds" and metric["period_table"] == "orders"
            ):
                raise ValueError("指标目录包含不支持的时间表关联")

            source_alias = "o" if source_table == "orders" else "f"
            source = f"{source_table} {source_alias}"
            period_table = metric["period_table"]
            needs_order_join = source_table == "refunds" and (
                period_table == "orders"
                or dimension == "region"
                or region_area is not None
            )
            if needs_order_join:
                source += (
                    " JOIN orders o ON o.tenant_id=f.tenant_id "
                    "AND o.order_id=f.order_id"
                )
            joins = ""
            dimension_select = ""
            group_clause = ""
            if dimension == "region" or region_area is not None:
                region = dimensions["region"]
                region_table = region["table"]
                region_column = region["column"]
                region_key = region["join_column"]
                if not all(
                    _IDENTIFIER.fullmatch(field)
                    for field in (region_table, region_column, region_key)
                ):
                    raise ValueError("指标目录包含无效维度字段")
                dimension_alias = "o" if source_table == "refunds" else source_alias
                joins = (
                    f" JOIN {region_table} r ON r.tenant_id="
                    f"{dimension_alias}.tenant_id AND r.{region_key}="
                    f"{dimension_alias}.{region_key}"
                )
                if dimension == "region":
                    dimension_select = f"r.{region_column} AS region, "
                    group_clause = " GROUP BY r." + region_column
            period_alias = "o" if period_table == "orders" else source_alias
            period_column = metric["period_date_column"]
            if dimension == "month":
                month = _month_expression(dialect, period_alias, period_column)
                dimension_select = f"{month} AS period, "
                group_clause = f" GROUP BY {month}"
            status_value = metric["status_value"].replace("'", "''")
            area_clause = (
                f" AND r.{area_filter['column']} = {area_literal}"
                if area_filter is not None
                else ""
            )
            sql = (
                f"SELECT {dimension_select}"
                f"SUM({source_alias}.{metric['amount_column']}) AS amount "
                f"FROM {source}{joins} "
                f"WHERE {period_alias}.{period_column} >= {start_sql} "
                f"AND {period_alias}.{period_column} < {end_sql} "
                f"AND {source_alias}.{metric['status_column']} = '{status_value}'"
                f"{area_clause}"
                f"{group_clause}"
            )
        elif calculation == "gross_margin_rate":
            if metric["id"] != "gross_margin_rate" or role != "admin":
                raise ValueError("当前身份无权使用该指标")
            precision = metric.get("precision")
            if not isinstance(precision, int) or not 0 <= precision <= 6:
                raise ValueError("指标目录包含无效精度")
            source = (
                "orders o "
                "JOIN order_items oi ON oi.tenant_id=o.tenant_id "
                "AND oi.order_id=o.order_id "
                "JOIN products p ON p.tenant_id=oi.tenant_id "
                "AND p.product_id=oi.product_id"
            )
            dimension_select = ""
            joins = ""
            group_clause = ""
            if dimension == "region" or region_area is not None:
                region = dimensions["region"]
                if (
                    region.get("table") != "regions"
                    or region.get("column") != "name"
                    or region.get("join_column") != "region_id"
                ):
                    raise ValueError("指标目录包含不支持的区域维度")
                joins = (
                    " JOIN regions r ON r.tenant_id=o.tenant_id "
                    "AND r.region_id=o.region_id"
                )
                if dimension == "region":
                    dimension_select = "r.name AS region, "
                    group_clause = " GROUP BY r.name"
            if dimension == "month":
                month = _month_expression(dialect, "o", "created_at")
                dimension_select = f"{month} AS period, "
                group_clause = f" GROUP BY {month}"
            sales = "SUM(oi.quantity*oi.unit_price_cents)"
            cost = "SUM(oi.quantity*p.internal_cost_cents)"
            area_clause = (
                f" AND r.{area_filter['column']} = {area_literal}"
                if area_filter is not None
                else ""
            )
            sql = (
                f"SELECT {dimension_select}"
                f"CASE WHEN {sales}=0 THEN NULL ELSE "
                f"ROUND(100.0*({sales}-{cost})/{sales}, {precision}) "
                f"END AS amount FROM {source}{joins} "
                f"WHERE o.created_at >= {start_sql} AND o.created_at < {end_sql} "
                f"AND o.status = 'completed'{area_clause}{group_clause}"
            )
        elif calculation in {"subtract", "percentage_ratio"}:
            dependencies = metric.get("dependencies", [])
            dependency_versions = metric.get("dependency_versions", {})
            if len(dependencies) != 2 or set(dependency_versions) != set(dependencies):
                raise ValueError("派生指标必须固定两个依赖版本")
            dependency_keys = [
                (dependency, dependency_versions[dependency])
                for dependency in dependencies
            ]
            dependency_aliases = [compile_metric(item) for item in dependency_keys]
            references = [
                f"{dependency_alias} AS d{index}"
                for index, dependency_alias in enumerate(dependency_aliases)
            ]
            dimension_select = ""
            if dimension is None:
                joins = " CROSS JOIN ".join(references)
            else:
                dimension_column = "period" if dimension == "month" else "region"
                anchor = 1 if calculation == "percentage_ratio" else 0
                joins = references[anchor]
                joins += "".join(
                    f" LEFT JOIN {reference} ON d{anchor}.{dimension_column}="
                    f"d{index}.{dimension_column}"
                    for index, reference in enumerate(references)
                    if index != anchor
                )
                dimension_select = (
                    f"d{anchor}.{dimension_column} AS {dimension_column}, "
                )
            if calculation == "subtract":
                formula = "d0.amount-COALESCE(d1.amount, 0)"
            else:
                precision = metric.get("precision")
                if not isinstance(precision, int) or not 0 <= precision <= 6:
                    raise ValueError("指标目录包含无效精度")
                formula = (
                    "CASE WHEN d1.amount=0 THEN NULL ELSE "
                    f"ROUND(100.0*COALESCE(d0.amount, 0)/d1.amount, "
                    f"{precision}) END"
                )
            sql = f"SELECT {dimension_select}{formula} AS amount FROM {joins}"
        else:
            raise ValueError("指标目录包含不支持的计算类型")

        visiting.remove(key)
        ctes.append(f"{alias} AS ({sql})")
        return alias

    root_alias = compile_metric(root_key)
    select_columns = []
    if dimension is not None:
        dimension_column = "period" if dimension == "month" else "region"
        result_dimension = "month" if dimension == "month" else dimension_column
        select_columns.append(f"{root_alias}.{dimension_column} AS {result_dimension}")
    result_column = _METRIC_RESULT_COLUMNS.get(metric_id, "value")
    select_columns.append(f"{root_alias}.amount AS {result_column}")
    sql = f"WITH {', '.join(ctes)} SELECT {', '.join(select_columns)} FROM {root_alias}"
    if dimension == "region":
        sql += f" ORDER BY {root_alias}.amount DESC, {root_alias}.region"
    elif dimension is not None:
        sql += f" ORDER BY {dimension_column}"
    result = {"sql": sql, "metric_id": metric_id, "metric_version": selected_version}
    if metric_id == "gross_margin_rate":
        result["trusted_plan"] = make_trusted_metric_plan(
            metric_id, selected_version, sql
        )
    return result


def make_metric_query(
    react_state: dict,
    database_connector: Any,
    execute_query: Any,
):
    """Build a tool that executes published metrics through ``sql_query``."""
    dialect = str(
        getattr(database_connector, "dialect", None)
        or getattr(database_connector, "db_type", "")
    ).lower()

    @tool(
        description=(
            "按当前已授权数据源的已发布指标目录确定性编译并执行指标查询；"
            "不会接受 SQL、表名或列名输入，执行仍经过 sql_query 的只读校验。"
            '参数: {"metric_id":"单个指标 ID，可选",'
            '"metric_ids":["多个指标 ID，可选"],"start_date":"YYYY-MM-DD",'
            '"end_date":"YYYY-MM-DD","dimension":"region/month，可选",'
            '"metric_version":"单指标显式版本，可选",'
            '"region_area":"服务端目录允许的大区，可选"}'
        )
    )
    def metric_query(
        start_date: str,
        end_date: str,
        metric_id: Optional[str] = None,
        metric_ids: Optional[List[str]] = None,
        dimension: Optional[str] = None,
        metric_version: Optional[str] = None,
        region_area: Optional[str] = None,
    ) -> str:
        started_at = time.monotonic()
        data_source_id = react_state.get("data_source_id")
        span = None
        status = "failed"
        try:
            try:
                span = root_tracer.start_span(
                    "agent.metric_query",
                    span_type=SpanType.AGENT,
                    metadata={"data_source_id": data_source_id},
                )
            except Exception:
                logger.debug("Unable to start metric query span", exc_info=True)

            catalog = load_database_metric_catalog(
                data_source_id, include_query_fields=True
            )
            if catalog is None:
                status = "catalog_missing"
                return json.dumps(
                    {
                        "chunks": [
                            {
                                "output_type": "text",
                                "content": "当前授权数据源没有可用的语义指标目录。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            catalog = filter_metric_catalog_for_role(catalog, react_state.get("role"))
            try:
                if metric_ids is not None and metric_id is not None:
                    raise ValueError("请使用 metric_id 或 metric_ids 中的一种")
                selected_ids = metric_ids if metric_ids is not None else [metric_id]
                if (
                    not isinstance(selected_ids, list)
                    or not 1 <= len(selected_ids) <= 4
                    or not all(isinstance(item, str) and item for item in selected_ids)
                    or len(set(selected_ids)) != len(selected_ids)
                    or (len(selected_ids) > 1 and dimension is not None)
                    or (len(selected_ids) > 1 and metric_version is not None)
                ):
                    raise ValueError("指标列表、维度或版本无效")
                queries = [
                    _compile_metric_sql(
                        catalog,
                        selected_id,
                        start_date,
                        end_date,
                        dialect=dialect,
                        dimension=dimension,
                        metric_version=metric_version,
                        region_area=region_area,
                        role=react_state.get("role"),
                    )
                    for selected_id in selected_ids
                ]
            except (KeyError, TypeError, ValueError):
                status = "invalid_request"
                return json.dumps(
                    {
                        "chunks": [
                            {
                                "output_type": "text",
                                "content": "指标目录、版本或查询范围无效，未执行查询。",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            results = []
            for query in queries:
                trusted_plan = query.get("trusted_plan")
                if trusted_plan is None:
                    result = json.loads(execute_query(sql=query["sql"]))
                else:
                    with use_trusted_metric_plan(trusted_plan):
                        result = json.loads(execute_query(sql=query["sql"]))
                if result.get("error"):
                    status = "query_failed"
                    return json.dumps(result, ensure_ascii=False)
                result_payload = result.get("result")
                if (
                    not isinstance(result_payload, dict)
                    or result_payload.get("type") != "sql_result"
                ):
                    status = "invalid_result"
                    return json.dumps(
                        {
                            "chunks": [
                                {
                                    "output_type": "text",
                                    "content": "指标查询未返回可验证结果。",
                                }
                            ],
                            "error": {"category": "invalid_result"},
                        },
                        ensure_ascii=False,
                    )
                results.append((query, result_payload, result))

            if len(results) == 1:
                query, _, result = results[0]
                status = "succeeded"
                result["metric"] = {
                    "id": query["metric_id"],
                    "version": query["metric_version"],
                    "catalog_version": catalog["catalog_version"],
                }
                return json.dumps(result, ensure_ascii=False)

            columns = []
            row = []
            metrics = []
            for query, result_payload, _ in results:
                if (
                    result_payload.get("truncated")
                    or result_payload.get("row_count") != 1
                    or len(result_payload.get("rows", [])) != 1
                    or len(result_payload.get("columns", [])) != 1
                    or len(result_payload["rows"][0]) != 1
                ):
                    status = "invalid_result"
                    return json.dumps(
                        {
                            "chunks": [
                                {
                                    "output_type": "text",
                                    "content": "组合指标查询必须各自返回单个汇总值。",
                                }
                            ],
                            "error": {"category": "invalid_result"},
                        },
                        ensure_ascii=False,
                    )
                columns.extend(result_payload["columns"])
                row.extend(result_payload["rows"][0])
                metrics.append(
                    {
                        "id": query["metric_id"],
                        "version": query["metric_version"],
                    }
                )
            status = "succeeded"
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": "已按发布口径计算组合指标。",
                        }
                    ],
                    "result": {
                        "type": "sql_result",
                        "columns": columns,
                        "rows": [row],
                        "row_count": 1,
                        "truncated": False,
                    },
                    "metrics": {
                        "catalog_version": catalog["catalog_version"],
                        "items": metrics,
                    },
                },
                ensure_ascii=False,
            )
        finally:
            if span is not None:
                try:
                    root_tracer.end_span(
                        span,
                        metadata={
                            "data_source_id": data_source_id,
                            "status": status,
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                        },
                    )
                except Exception:
                    logger.debug("Unable to end metric query span", exc_info=True)

    return metric_query
