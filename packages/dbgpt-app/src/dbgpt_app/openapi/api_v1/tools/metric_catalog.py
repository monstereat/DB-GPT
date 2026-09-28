"""Datasource-scoped read-only metric catalog tool."""

import json
import logging
import time
from typing import Optional

from dbgpt.agent.resource.tool.base import tool
from dbgpt.util.tracer import SpanType, root_tracer

from ..business_context import (
    filter_metric_catalog_for_role,
    load_database_metric_catalog,
)

logger = logging.getLogger(__name__)


def make_metric_catalog(react_state: dict):
    """Build a catalog lookup tool bound to the authorized datasource name."""

    @tool(
        description=(
            "查询当前已授权数据源的服务端指标目录，返回已发布指标定义、单位、"
            "默认版本和固定依赖。使用目录中的定义生成 SQL，再交给 sql_query 执行。"
            '参数: {"metric_id": "指标 ID，可选", "metric_version": "版本，可选"}'
        )
    )
    def metric_catalog(
        metric_id: Optional[str] = None, metric_version: Optional[str] = None
    ) -> str:
        database_name = react_state.get("data_source_id")
        started_at = time.monotonic()
        span = None
        status = "failed"
        try:
            try:
                span = root_tracer.start_span(
                    "agent.metric_catalog",
                    span_type=SpanType.AGENT,
                    metadata={"data_source_id": database_name},
                )
            except Exception:
                logger.debug("Unable to start metric catalog span", exc_info=True)

            catalog = load_database_metric_catalog(database_name)
            if catalog is None:
                status = "catalog_missing"
                content = "当前授权数据源没有可用的服务端指标目录。"
                return json.dumps(
                    {"chunks": [{"output_type": "text", "content": content}]},
                    ensure_ascii=False,
                )

            catalog = filter_metric_catalog_for_role(catalog, react_state.get("role"))
            defaults = catalog["default_metric_versions"]
            metrics = catalog["metrics"]
            if metric_id:
                metrics = [item for item in metrics if item["id"] == metric_id]
                if metric_version:
                    metrics = [
                        item for item in metrics if item["version"] == metric_version
                    ]
                else:
                    default_version = defaults.get(metric_id)
                    metrics = [
                        item for item in metrics if item["version"] == default_version
                    ]
            elif metric_version:
                metrics = [
                    item for item in metrics if item["version"] == metric_version
                ]

            metrics = metrics[:25]
            if not metrics:
                status = "not_published"
                content = "指标或版本未在服务端目录中发布。"
                return json.dumps(
                    {"chunks": [{"output_type": "text", "content": content}]},
                    ensure_ascii=False,
                )

            result = {
                "catalog_version": catalog["catalog_version"],
                "metrics": [
                    {
                        "id": item["id"],
                        "version": item["version"],
                        "name": item["name"],
                        "calculation": item["calculation"],
                        "unit": item["unit"],
                        "definition": item["definition"],
                        "aliases": item.get("aliases", []),
                        "dependencies": item["dependencies"],
                        "dependency_versions": item["dependency_versions"],
                        "default_version": defaults.get(item["id"]),
                    }
                    for item in metrics
                ],
            }
            if catalog.get("default_year") is not None:
                result["default_year"] = catalog["default_year"]
            status = "succeeded"
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "json",
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    ],
                    "catalog": result,
                },
                ensure_ascii=False,
            )
        finally:
            if span is not None:
                try:
                    root_tracer.end_span(
                        span,
                        metadata={
                            "data_source_id": database_name,
                            "status": status,
                            "elapsed_ms": int((time.monotonic() - started_at) * 1000),
                        },
                    )
                except Exception:
                    logger.debug("Unable to end metric catalog span", exc_info=True)

    return metric_catalog
