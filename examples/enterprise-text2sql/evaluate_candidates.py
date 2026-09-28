"""Reproducible guarded Text-to-SQL candidate evaluation for the ecommerce MVP.

This evaluates supplied SQL, NOT an LLM's ability to write it. All SQL still
passes through GuardedSQLiteQuery with a server-owned tenant/column scope.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from ecommerce_demo import (
    EXPECTED_TENANT_A,
    GOLD_ORDER_SENSITIVE,
    GOLD_QUERIES,
    GOLD_QUESTIONS,
    create_demo_database,
    gold_rows_match,
    tenant_executor,
)
from guarded_query import GuardedSQLiteQuery, QueryRejected

from dbgpt.datasource.sql_guard import (
    SQLQueryFailure,
    execute_read_only_query,
    validate_read_only_sql,
)

MAX_CANDIDATES_BYTES = 256 * 1024
MAX_SQL_LENGTH = 10000
GOLD_CATEGORIES = {item["id"]: item["category"] for item in GOLD_QUESTIONS}
DIALECT_SECURITY_EXPECTATIONS = {
    "postgresql": {
        "read_only_select": "accepted",
        "delete_statement": "rejected",
        "write_cte": "rejected",
        "row_lock": "rejected",
        "copy_export": "rejected",
        "server_file_read": "rejected",
        "resource_sleep": "rejected",
        "cross_session_notify": "rejected",
        "session_setting": "rejected",
        "multiple_statements": "rejected",
    },
    "mysql": {
        "read_only_select": "accepted",
        "delete_statement": "rejected",
        "write_cte": "rejected",
        "into_outfile": "rejected",
        "load_file": "rejected",
        "resource_sleep": "rejected",
        "named_lock": "rejected",
        "benchmark": "rejected",
        "last_insert_id_expression": "rejected",
        "multiple_statements": "rejected",
    },
}
DIALECT_SECURITY_CATEGORIES = {
    "read_only_select": "read_only_control",
    "delete_statement": "write_or_export",
    "write_cte": "write_or_export",
    "row_lock": "session_side_effects",
    "copy_export": "write_or_export",
    "server_file_read": "server_file_access",
    "resource_sleep": "resource_exhaustion",
    "cross_session_notify": "session_side_effects",
    "session_setting": "session_side_effects",
    "multiple_statements": "multiple_statements",
    "into_outfile": "write_or_export",
    "load_file": "server_file_access",
    "named_lock": "session_side_effects",
    "benchmark": "resource_exhaustion",
    "last_insert_id_expression": "session_side_effects",
}
SECURITY_EXPECTATIONS = {
    "sensitive_column": "rejected",
    "cross_tenant_column": "rejected",
    "write_statement": "rejected",
    "syntax_error": "rejected",
    "foreign_region_scope": "empty_result",
    "sensitive_aggregation": "rejected",
    "cte_table_shadow": "rejected",
    "multiple_statements": "rejected",
    "extension_function": "rejected",
    "cte_hidden_column": "rejected",
    "recursive_cte": "rejected",
    "direct_main_table": "rejected",
    "pragma_schema_introspection": "rejected",
    "sqlite_catalog_access": "rejected",
    "sqlite_pragma_table_valued": "rejected",
    "sqlite_file_read_function": "rejected",
    "sqlite_file_write_function": "rejected",
    "sqlite_pragma_table_list": "rejected",
    "sqlite_pragma_function_list": "rejected",
}
SECURITY_CATEGORIES = {
    "sensitive_column": "sensitive_data",
    "sensitive_aggregation": "sensitive_data",
    "cte_hidden_column": "sensitive_data",
    "cross_tenant_column": "tenant_boundary",
    "foreign_region_scope": "tenant_boundary",
    "write_statement": "read_only_and_syntax",
    "syntax_error": "read_only_and_syntax",
    "multiple_statements": "read_only_and_syntax",
    "cte_table_shadow": "query_structure",
    "recursive_cte": "query_structure",
    "direct_main_table": "query_structure",
    "pragma_schema_introspection": "schema_introspection",
    "sqlite_catalog_access": "schema_introspection",
    "sqlite_pragma_table_valued": "schema_introspection",
    "sqlite_pragma_table_list": "schema_introspection",
    "sqlite_pragma_function_list": "schema_introspection",
    "extension_function": "unsafe_functions",
    "sqlite_file_read_function": "unsafe_functions",
    "sqlite_file_write_function": "unsafe_functions",
}
AMBIGUITY_CASES = json.loads(
    Path(__file__).with_name("ambiguity_cases.json").read_text(encoding="utf-8")
)
AMBIGUITY_EXPECTATIONS = {
    case["id"]: set(case["expected_missing_fields"]) for case in AMBIGUITY_CASES
}
AMBIGUITY_FIELDS = {"metric", "time_range", "comparison_basis", "dimension"}
AUTHORIZATION_CASES = json.loads(
    Path(__file__)
    .with_name("multiturn_authorization_cases.json")
    .read_text(encoding="utf-8")
)
MAX_AUTHORIZATION_TURNS = 5
SCHEMA_SECURITY_EXPECTATIONS = {
    "confidential_column": "rejected",
    "aliased_confidential_column": "rejected",
    "cte_hidden_column": "rejected",
    "scalar_subquery_column": "rejected",
    "table_wildcard": "rejected",
    "qualified_table_wildcard": "rejected",
    "tenant_key_projection": "rejected",
    "tenant_key_grouping": "rejected",
    "safe_count_star": "accepted",
    "safe_tenant_key_join": "accepted",
    "unregistered_view_alias": "rejected",
    "unregistered_view_wildcard": "rejected",
    "registered_safe_view": "accepted",
    "registered_view_sensitive_definition": "rejected",
    "registered_view_missing_definition": "rejected",
}
SCHEMA_SECURITY_CATEGORIES = {
    "confidential_column": "sensitive_columns",
    "aliased_confidential_column": "sensitive_columns",
    "cte_hidden_column": "sensitive_columns",
    "scalar_subquery_column": "sensitive_columns",
    "table_wildcard": "wildcard_exposure",
    "qualified_table_wildcard": "wildcard_exposure",
    "tenant_key_projection": "tenant_key_protection",
    "tenant_key_grouping": "tenant_key_protection",
    "safe_count_star": "safe_query_shapes",
    "safe_tenant_key_join": "safe_query_shapes",
    "unregistered_view_alias": "unregistered_objects",
    "unregistered_view_wildcard": "unregistered_objects",
    "registered_safe_view": "view_definition_audit",
    "registered_view_sensitive_definition": "view_definition_audit",
    "registered_view_missing_definition": "view_definition_audit",
}
ROW_SCOPE_CASES = {
    "tenant_scope": {
        "tenant_id": "tenant-a",
        "role": "normal",
        "status": "returned_rows",
        "expected_rows": 8,
    },
    "sales_direct_region": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "a-gz",
        "status": "returned_rows",
        "expected_rows": 4,
    },
    "sales_refunds_via_orders": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "a-gz",
        "status": "returned_rows",
        "expected_rows": 3,
    },
    "sales_items_via_orders": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "a-gz",
        "status": "returned_rows",
        "expected_rows": 5,
    },
    "sales_products_via_items": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "a-gz",
        "status": "returned_rows",
        "expected_rows": 3,
    },
    "tenant_or_bypass": {
        "tenant_id": "tenant-a",
        "role": "normal",
        "status": "returned_rows",
        "expected_rows": 8,
    },
    "region_or_bypass": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "region_id": "a-gz",
        "status": "returned_rows",
        "expected_rows": 4,
    },
    "missing_tenant": {"role": "normal", "status": "rejected"},
    "missing_sales_region": {
        "tenant_id": "tenant-a",
        "role": "sales",
        "status": "rejected",
    },
    "unregistered_table": {
        "tenant_id": "tenant-a",
        "role": "normal",
        "status": "rejected",
    },
    "unregistered_schema": {
        "tenant_id": "tenant-a",
        "role": "normal",
        "status": "rejected",
    },
}
ROW_SCOPE_CATEGORIES = {
    "tenant_scope": "tenant_isolation",
    "sales_direct_region": "region_scope",
    "sales_refunds_via_orders": "region_scope",
    "sales_items_via_orders": "region_scope",
    "sales_products_via_items": "region_scope",
    "tenant_or_bypass": "bypass_resistance",
    "region_or_bypass": "bypass_resistance",
    "missing_tenant": "missing_identity",
    "missing_sales_region": "missing_identity",
    "unregistered_table": "unregistered_objects",
    "unregistered_schema": "unregistered_objects",
}
METRIC_CASES = {
    "sales_q2": {
        "metric_id": "sales_amount",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(77000,)],
    },
    "refund_event_date": {
        "metric_id": "paid_refund_amount",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(4700,)],
    },
    "refund_order_cohort": {
        "metric_id": "paid_refund_amount",
        "version": "2.0.0",
        "start_date": "2026-06-18",
        "end_date": "2026-06-19",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(1000,)],
    },
    "net_sales_event_date": {
        "metric_id": "net_sales_amount",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(72300,)],
    },
    "net_sales_order_cohort": {
        "metric_id": "net_sales_amount",
        "version": "2.0.0",
        "start_date": "2026-06-18",
        "end_date": "2026-06-19",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(19000,)],
    },
    "refund_rate_event_date": {
        "metric_id": "refund_rate",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(6.1,)],
    },
    "refund_rate_order_cohort": {
        "metric_id": "refund_rate",
        "version": "2.0.0",
        "start_date": "2026-06-18",
        "end_date": "2026-06-19",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "executed",
        "expected": [(5.0,)],
    },
    "sales_by_region": {
        "metric_id": "sales_amount",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": "region",
        "role": "sales",
        "region_id": "a-gz",
        "status": "executed",
        "expected": [("Guangzhou", 45000)],
    },
    "gross_margin_admin": {
        "metric_id": "gross_margin_rate",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "admin",
        "region_id": None,
        "status": "executed",
        "expected": [(43.12,)],
    },
    "gross_margin_non_admin": {
        "metric_id": "gross_margin_rate",
        "version": "1.0.0",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "dimension": None,
        "role": "normal",
        "region_id": None,
        "status": "rejected",
        "expected": None,
    },
    "gross_margin_zero_sales": {
        "metric_id": "gross_margin_rate",
        "version": "1.0.0",
        "start_date": "2026-10-01",
        "end_date": "2026-11-01",
        "dimension": None,
        "role": "admin",
        "region_id": None,
        "status": "executed",
        "expected": [(None,)],
    },
}
METRIC_CATEGORIES = {
    "sales_q2": "base_metric",
    "refund_event_date": "time_and_version_semantics",
    "refund_order_cohort": "time_and_version_semantics",
    "net_sales_event_date": "time_and_version_semantics",
    "net_sales_order_cohort": "time_and_version_semantics",
    "refund_rate_event_date": "time_and_version_semantics",
    "refund_rate_order_cohort": "time_and_version_semantics",
    "sales_by_region": "tenant_region_scope",
    "gross_margin_admin": "restricted_metric",
    "gross_margin_non_admin": "role_authorization",
    "gross_margin_zero_sales": "zero_denominator",
}


def _category_scorecard(
    outcomes: list[dict], category_by_case: Mapping[str, str], case_key: str
) -> tuple[dict, float]:
    """Summarize case accuracy by fixed category and return its macro average."""
    grouped: dict[str, list[dict]] = {}
    for outcome in outcomes:
        case_id = outcome[case_key]
        category = category_by_case[case_id]
        outcome["category"] = category
        grouped.setdefault(category, []).append(outcome)

    by_category = {}
    for category, category_outcomes in grouped.items():
        count = len(category_outcomes)
        passed = sum(item["passed"] for item in category_outcomes)
        by_category[category] = {
            "case_count": count,
            "passed": passed,
            "failed": count - passed,
            "missing": sum(item["status"] == "missing" for item in category_outcomes),
            "pass_rate": passed / count if count else 0,
        }
    macro_average = (
        sum(item["pass_rate"] for item in by_category.values()) / len(by_category)
        if by_category
        else 0
    )
    return by_category, macro_average


def evaluate_candidates(
    executor: GuardedSQLiteQuery,
    candidates: Mapping[str, str],
    expected: Mapping[str, dict] = EXPECTED_TENANT_A,
) -> dict:
    """Return a deterministic scorecard without echoing SQL or data values.

    The expected dataset must match the server-side executor's tenant. Model-
    generated SQL and question IDs are untrusted input; neither can set ACL.
    """
    outcomes = []
    for question in GOLD_QUERIES:
        category = GOLD_CATEGORIES[question]
        order_sensitive = GOLD_ORDER_SENSITIVE[question]
        sql = candidates.get(question)
        if not isinstance(sql, str) or not sql.strip():
            outcomes.append(
                {
                    "question": question,
                    "category": category,
                    "order_sensitive": order_sensitive,
                    "status": "missing",
                    "passed": False,
                }
            )
            continue
        if len(sql) > MAX_SQL_LENGTH:
            outcomes.append(
                {
                    "question": question,
                    "category": category,
                    "order_sensitive": order_sensitive,
                    "status": "rejected",
                    "passed": False,
                }
            )
            continue

        fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            actual = executor.run(sql)
        except QueryRejected:
            outcomes.append(
                {
                    "question": question,
                    "category": category,
                    "order_sensitive": order_sensitive,
                    "status": "rejected",
                    "passed": False,
                    "query_sha256": fingerprint,
                }
            )
            continue

        passed = actual["columns"] == expected[question]["columns"] and gold_rows_match(
            question, actual["rows"], expected[question]["rows"]
        )
        outcomes.append(
            {
                "question": question,
                "category": category,
                "order_sensitive": order_sensitive,
                "status": "correct" if passed else "incorrect",
                "passed": passed,
                "query_sha256": fingerprint,
                "duration_ms": actual["duration_ms"],
                "returned_rows": actual["returned_rows"],
            }
        )

    count = len(outcomes)
    correct = sum(item["passed"] for item in outcomes)
    by_category = {}
    for category in sorted(set(GOLD_CATEGORIES.values())):
        category_outcomes = [item for item in outcomes if item["category"] == category]
        category_count = len(category_outcomes)
        category_correct = sum(item["passed"] for item in category_outcomes)
        by_category[category] = {
            "question_count": category_count,
            "correct": category_correct,
            "incorrect": sum(
                item["status"] == "incorrect" for item in category_outcomes
            ),
            "rejected": sum(item["status"] == "rejected" for item in category_outcomes),
            "missing": sum(item["status"] == "missing" for item in category_outcomes),
            "accuracy": category_correct / category_count if category_count else 0,
        }
    return {
        "question_count": count,
        "correct": correct,
        "incorrect": sum(item["status"] == "incorrect" for item in outcomes),
        "rejected": sum(item["status"] == "rejected" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "result_accuracy": correct / count if count else 0,
        "by_category": by_category,
        "macro_average_accuracy": (
            sum(item["accuracy"] for item in by_category.values()) / len(by_category)
            if by_category
            else 0
        ),
        "cases": outcomes,
        "note": (
            "Guarded result equality on fixed synthetic data; "
            "not a live model benchmark."
        ),
    }


def evaluate_security_candidates(
    executor: GuardedSQLiteQuery, candidates: Mapping[str, str]
) -> dict:
    """Score required query-policy denials and server-side scope enforcement."""
    outcomes = []
    for case_id, expected_status in SECURITY_EXPECTATIONS.items():
        sql = candidates.get(case_id)
        if not isinstance(sql, str) or not sql.strip():
            outcomes.append(
                {
                    "case": case_id,
                    "category": SECURITY_CATEGORIES[case_id],
                    "status": "missing",
                    "passed": False,
                }
            )
            continue
        if len(sql) > MAX_SQL_LENGTH:
            outcomes.append(
                {
                    "case": case_id,
                    "category": SECURITY_CATEGORIES[case_id],
                    "status": "rejected",
                    "passed": False,
                }
            )
            continue

        fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            actual = executor.run(sql)
        except QueryRejected:
            actual_status = "rejected"
            passed = expected_status == actual_status
            returned_rows = None
        else:
            actual_status = "empty_result" if not actual["rows"] else "returned_rows"
            passed = expected_status == actual_status
            returned_rows = actual["returned_rows"]
        outcomes.append(
            {
                "case": case_id,
                "category": SECURITY_CATEGORIES[case_id],
                "status": actual_status,
                "passed": passed,
                "query_sha256": fingerprint,
                "returned_rows": returned_rows,
            }
        )

    count = len(outcomes)
    passed = sum(item["passed"] for item in outcomes)
    by_category = {}
    for category in sorted(set(SECURITY_CATEGORIES.values())):
        category_outcomes = [item for item in outcomes if item["category"] == category]
        category_count = len(category_outcomes)
        category_passed = sum(item["passed"] for item in category_outcomes)
        by_category[category] = {
            "case_count": category_count,
            "passed": category_passed,
            "failed": category_count - category_passed,
            "rejected": sum(item["status"] == "rejected" for item in category_outcomes),
            "scope_filtered": sum(
                item["status"] == "empty_result" for item in category_outcomes
            ),
            "missing": sum(item["status"] == "missing" for item in category_outcomes),
            "pass_rate": category_passed / category_count if category_count else 0,
        }
    return {
        "case_count": count,
        "passed": passed,
        "failed": count - passed,
        "rejected": sum(item["status"] == "rejected" for item in outcomes),
        "scope_filtered": sum(item["status"] == "empty_result" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "pass_rate": passed / count if count else 0,
        "by_category": by_category,
        "macro_average_pass_rate": (
            sum(item["pass_rate"] for item in by_category.values()) / len(by_category)
            if by_category
            else 0
        ),
        "cases": outcomes,
        "note": "Policy denial and tenant-scope checks on fixed synthetic data.",
    }


def load_candidates(path: str | Path) -> dict[str, str]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Candidate JSON file exceeds the configured size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(GOLD_QUERIES):
        raise ValueError("Candidates must map known question IDs to SQL strings")
    if any(
        not isinstance(value, str) or len(value) > MAX_SQL_LENGTH
        for value in raw.values()
    ):
        raise ValueError("Candidate SQL values must be strings within the size limit")
    return raw


def load_security_candidates(path: str | Path) -> dict[str, str]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Security candidate JSON file exceeds the configured size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(SECURITY_EXPECTATIONS):
        raise ValueError("Security candidates must map known case IDs to SQL strings")
    if any(
        not isinstance(value, str) or len(value) > MAX_SQL_LENGTH
        for value in raw.values()
    ):
        raise ValueError(
            "Security candidate SQL values must be strings within the size limit"
        )
    return raw


def load_dialect_security_candidates(path: str | Path) -> dict[str, dict[str, str]]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Dialect security candidate JSON exceeds the size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != set(DIALECT_SECURITY_EXPECTATIONS):
        raise ValueError("Dialect candidates must provide each supported dialect")
    normalized = {}
    for dialect, candidates in raw.items():
        expectations = DIALECT_SECURITY_EXPECTATIONS[dialect]
        if (
            not isinstance(candidates, dict)
            or set(candidates) - set(expectations)
            or any(
                not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_LENGTH
                for sql in candidates.values()
            )
        ):
            raise ValueError("Dialect candidates must map known cases to bounded SQL")
        normalized[dialect] = candidates
    return normalized


def evaluate_dialect_security_candidates(
    candidates: Mapping[str, Mapping[str, str]],
) -> dict:
    """Score cross-dialect AST policy cases without opening a database connection."""

    def summarize(outcomes: list[dict]) -> dict:
        case_count = len(outcomes)
        passed_count = sum(item["passed"] for item in outcomes)
        by_category = {}
        for category in sorted({item["category"] for item in outcomes}):
            items = [item for item in outcomes if item["category"] == category]
            category_passed = sum(item["passed"] for item in items)
            by_category[category] = {
                "case_count": len(items),
                "passed": category_passed,
                "failed": len(items) - category_passed,
                "pass_rate": category_passed / len(items) if items else 0,
            }
        macro_average = (
            sum(item["pass_rate"] for item in by_category.values()) / len(by_category)
            if by_category
            else 0
        )
        return {
            "case_count": case_count,
            "passed": passed_count,
            "failed": case_count - passed_count,
            "accepted": sum(item.get("decision") == "accepted" for item in outcomes),
            "rejected": sum(item.get("decision") == "rejected" for item in outcomes),
            "missing": sum(item["status"] == "missing" for item in outcomes),
            "pass_rate": passed_count / case_count if case_count else 0,
            "macro_average_pass_rate": macro_average,
            "by_category": by_category,
            "cases": outcomes,
        }

    dialect_reports = {}
    all_outcomes = []
    for dialect, expectations in DIALECT_SECURITY_EXPECTATIONS.items():
        supplied = candidates.get(dialect, {})
        outcomes = []
        for case_id, expected in expectations.items():
            category = DIALECT_SECURITY_CATEGORIES[case_id]
            sql = supplied.get(case_id)
            if not isinstance(sql, str) or not sql.strip():
                outcomes.append(
                    {
                        "case": case_id,
                        "category": category,
                        "status": "missing",
                        "passed": False,
                    }
                )
                continue
            fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            try:
                validate_read_only_sql(sql, SimpleNamespace(dialect=dialect))
            except SQLQueryFailure:
                actual = "rejected"
            else:
                actual = "accepted"
            passed = actual == expected
            outcomes.append(
                {
                    "case": case_id,
                    "category": category,
                    "status": "correct" if passed else actual,
                    "decision": actual,
                    "passed": passed,
                    "query_sha256": fingerprint,
                }
            )
        dialect_reports[dialect] = summarize(outcomes)
        all_outcomes.extend({**outcome, "dialect": dialect} for outcome in outcomes)
    overall = summarize(all_outcomes)
    return {
        "dialect_count": len(dialect_reports),
        "case_count": overall["case_count"],
        "passed": overall["passed"],
        "failed": overall["failed"],
        "pass_rate": overall["pass_rate"],
        "macro_average_pass_rate": overall["macro_average_pass_rate"],
        "by_category": overall["by_category"],
        "dialects": dialect_reports,
        "note": (
            "SQLGlot AST policy validation only; no PostgreSQL/MySQL server, "
            "grants, row policies, timeouts, or execution behavior tested."
        ),
    }


def load_schema_security_candidates(path: str | Path) -> dict[str, str]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Schema security candidate JSON exceeds the size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(SCHEMA_SECURITY_EXPECTATIONS):
        raise ValueError("Schema security candidates must map known case IDs to SQL")
    if any(
        not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_LENGTH
        for sql in raw.values()
    ):
        raise ValueError("Schema security candidate SQL must be bounded strings")
    return raw


def evaluate_schema_security_candidates(candidates: Mapping[str, str]) -> dict:
    """Score App schema-metadata column policies without opening a database."""
    app_source = Path(__file__).resolve().parents[2] / "packages/dbgpt-app/src"
    if str(app_source) not in sys.path:
        sys.path.insert(0, str(app_source))
    policy_module = importlib.import_module("dbgpt_app.openapi.api_v1.business_context")
    schema_path = Path(__file__).with_name("schema_metadata.json").resolve()
    mapping = json.dumps({"enterprise-ecommerce": str(schema_path)})
    policy = policy_module.load_database_schema_policy(
        "enterprise-ecommerce", mapping_json=mapping
    )
    policy["views"].update(
        {"public_product_catalog", "unsafe_product_catalog", "missing_product_catalog"}
    )
    policy["tables"].update(
        {
            "public_product_catalog": {"product_id"},
            "unsafe_product_catalog": {"product_id"},
            "missing_product_catalog": {"product_id"},
        }
    )
    policy["view_definitions"].update(
        {
            "public_product_catalog": "SELECT product_id FROM products",
            "unsafe_product_catalog": "SELECT internal_cost_cents FROM products",
        }
    )
    policy["column_classifications"].update(
        {
            "public_product_catalog": {"product_id": "business"},
            "unsafe_product_catalog": {"product_id": "business"},
            "missing_product_catalog": {"product_id": "business"},
        }
    )
    policy["queryable_columns"].update(
        {
            "public_product_catalog": {"product_id"},
            "unsafe_product_catalog": {"product_id"},
            "missing_product_catalog": {"product_id"},
        }
    )
    outcomes = []
    for case_id, expected in SCHEMA_SECURITY_EXPECTATIONS.items():
        sql = candidates.get(case_id)
        if not isinstance(sql, str) or not sql.strip():
            outcomes.append({"case": case_id, "status": "missing", "passed": False})
            continue
        fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            policy_module.validate_query_columns(sql, policy, dialect="sqlite")
        except ValueError:
            actual = "rejected"
        else:
            actual = "accepted"
        passed = actual == expected
        outcomes.append(
            {
                "case": case_id,
                "status": "correct" if passed else actual,
                "decision": actual,
                "passed": passed,
                "query_sha256": fingerprint,
            }
        )
    count = len(outcomes)
    passed = sum(item["passed"] for item in outcomes)
    by_category, macro_average_pass_rate = _category_scorecard(
        outcomes, SCHEMA_SECURITY_CATEGORIES, "case"
    )
    return {
        "case_count": count,
        "passed": passed,
        "failed": count - passed,
        "accepted": sum(item.get("decision") == "accepted" for item in outcomes),
        "rejected": sum(item.get("decision") == "rejected" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "pass_rate": passed / count if count else 0,
        "by_category": by_category,
        "macro_average_pass_rate": macro_average_pass_rate,
        "cases": outcomes,
        "note": (
            "Schema metadata AST checks include registered projection views and reject "
            "unsafe definitions; view tenant execution, database grants, and other "
            "query entrypoints require separate verification."
        ),
    }


def load_row_scope_candidates(path: str | Path) -> dict[str, str]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Row-scope candidate JSON exceeds the size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(ROW_SCOPE_CASES):
        raise ValueError("Row-scope candidates must map known case IDs to SQL")
    if any(
        not isinstance(sql, str) or not sql.strip() or len(sql) > MAX_SQL_LENGTH
        for sql in raw.values()
    ):
        raise ValueError("Row-scope candidate SQL must be bounded strings")
    return raw


def evaluate_row_scope_candidates(
    database_path: str | Path, candidates: Mapping[str, str]
) -> dict:
    """Execute fixed row-policy candidates through the ReAct policy and SQL guard."""
    import sqlite3

    app_source = Path(__file__).resolve().parents[2] / "packages/dbgpt-app/src"
    if str(app_source) not in sys.path:
        sys.path.insert(0, str(app_source))
    policy_module = importlib.import_module("dbgpt_app.openapi.api_v1.business_context")
    schema_path = Path(__file__).with_name("schema_metadata.json").resolve()
    mapping = json.dumps({"enterprise-ecommerce": str(schema_path)})
    policy = policy_module.load_database_schema_policy(
        "enterprise-ecommerce", mapping_json=mapping
    )
    connection = sqlite3.connect(str(database_path))

    class _SQLiteConnector:
        dialect = "sqlite"

        def query_ex(self, sql: str, timeout: int | None = None):
            cursor = connection.execute(sql)
            return [column[0] for column in cursor.description], cursor.fetchall()

    connector = _SQLiteConnector()
    outcomes = []
    try:
        for case_id, case in ROW_SCOPE_CASES.items():
            sql = candidates.get(case_id)
            if not isinstance(sql, str) or not sql.strip():
                outcomes.append({"case": case_id, "status": "missing", "passed": False})
                continue

            fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            try:
                policy_module.validate_query_columns(sql, policy, dialect="sqlite")
                scoped_sql = policy_module.apply_database_row_scope(
                    sql,
                    policy,
                    tenant_id=case.get("tenant_id"),
                    role=case.get("role"),
                    region_id=case.get("region_id"),
                    dialect="sqlite",
                )
                result = execute_read_only_query(connector, scoped_sql)
                actual_status = "empty_result" if not result.rows else "returned_rows"
                returned_rows = len(result.rows)
            except (SQLQueryFailure, ValueError):
                actual_status = "rejected"
                returned_rows = None
            expected_status = case["status"]
            passed = actual_status == expected_status and (
                case.get("expected_rows") is None
                or returned_rows == case["expected_rows"]
            )
            outcomes.append(
                {
                    "case": case_id,
                    "status": actual_status,
                    "passed": passed,
                    "query_sha256": fingerprint,
                    "returned_rows": returned_rows,
                }
            )
    finally:
        connection.close()

    count = len(outcomes)
    passed = sum(item["passed"] for item in outcomes)
    by_category, macro_average_pass_rate = _category_scorecard(
        outcomes, ROW_SCOPE_CATEGORIES, "case"
    )
    return {
        "case_count": count,
        "passed": passed,
        "failed": count - passed,
        "rejected": sum(item["status"] == "rejected" for item in outcomes),
        "scope_filtered": sum(item["status"] == "empty_result" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "pass_rate": passed / count if count else 0,
        "by_category": by_category,
        "macro_average_pass_rate": macro_average_pass_rate,
        "cases": outcomes,
        "note": (
            "Fixed SQL executed through the ReAct tenant/region AST policy on "
            "synthetic SQLite data; not a live Agent or production RLS benchmark."
        ),
    }


def load_metric_candidates(path: str | Path) -> dict[str, dict[str, object]]:
    """Load bounded metric requests; identities and expected results stay local."""
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Metric candidate JSON exceeds the configured size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    allowed_fields = {
        "metric_id",
        "metric_version",
        "start_date",
        "end_date",
        "dimension",
    }
    if not isinstance(raw, dict) or set(raw) - set(METRIC_CASES):
        raise ValueError("Metric candidates must map known case IDs to requests")
    for candidate in raw.values():
        if (
            not isinstance(candidate, dict)
            or set(candidate) - allowed_fields
            or not {"metric_id", "start_date", "end_date"}.issubset(candidate)
            or any(
                field != "dimension" and (not isinstance(value, str) or len(value) > 64)
                for field, value in candidate.items()
            )
            or (
                candidate.get("dimension") is not None
                and (
                    not isinstance(candidate["dimension"], str)
                    or candidate["dimension"] not in {"region", "month"}
                )
            )
        ):
            raise ValueError("Metric candidate requests contain invalid fields")
    return raw


def _metric_rows_match(actual: list[tuple], expected: list[tuple]) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected):
        if len(actual_row) != len(expected_row):
            return False
        for actual_value, expected_value in zip(actual_row, expected_row):
            if isinstance(expected_value, (int, float)) and not isinstance(
                expected_value, bool
            ):
                if not isinstance(actual_value, (int, float)) or not math.isclose(
                    actual_value, expected_value, rel_tol=0, abs_tol=1e-9
                ):
                    return False
            elif actual_value != expected_value:
                return False
    return True


def evaluate_metric_candidates(
    database_path: str | Path, candidates: Mapping[str, dict[str, object]]
) -> dict:
    """Run metric requests through the App compiler, policy and read-only gateway."""
    import sqlite3

    app_source = Path(__file__).resolve().parents[2] / "packages/dbgpt-app/src"
    if str(app_source) not in sys.path:
        sys.path.insert(0, str(app_source))
    context_module = importlib.import_module(
        "dbgpt_app.openapi.api_v1.business_context"
    )
    compiler_module = importlib.import_module(
        "dbgpt_app.openapi.api_v1.tools.metric_query"
    )
    schema_path = Path(__file__).with_name("schema_metadata.json").resolve()
    catalog_path = Path(__file__).with_name("metric_catalog.json").resolve()
    schema_mapping = json.dumps({"enterprise-ecommerce": str(schema_path)})
    catalog_mapping = json.dumps({"enterprise-ecommerce": str(catalog_path)})
    env_name = "DBGPT_DATABASE_SCHEMA_FILES"
    previous_mapping = os.environ.get(env_name)
    os.environ[env_name] = schema_mapping
    catalog = context_module.load_database_metric_catalog(
        "enterprise-ecommerce",
        mapping_json=catalog_mapping,
        include_query_fields=True,
    )
    if catalog is None:
        if previous_mapping is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_mapping
        raise ValueError("The server-owned metric catalog is unavailable")

    connection = sqlite3.connect(str(database_path))

    class _SQLiteConnector:
        dialect = "sqlite"

        def query_ex(self, sql: str, timeout: int | None = None):
            cursor = connection.execute(sql)
            return [column[0] for column in cursor.description], cursor.fetchall()

    connector = _SQLiteConnector()
    outcomes = []
    try:
        for case_id, case in METRIC_CASES.items():
            candidate = candidates.get(case_id)
            if candidate is None:
                outcomes.append({"case": case_id, "status": "missing", "passed": False})
                continue

            requested_version = candidate.get("metric_version")
            request_matches = (
                candidate.get("metric_id") == case["metric_id"]
                and candidate.get("start_date") == case["start_date"]
                and candidate.get("end_date") == case["end_date"]
                and candidate.get("dimension") == case["dimension"]
                and (requested_version or case["version"]) == case["version"]
            )
            fingerprint = None
            returned_rows = None
            metric_version = None
            try:
                role_catalog = context_module.filter_metric_catalog_for_role(
                    catalog, case["role"]
                )
                compiled = compiler_module._compile_metric_sql(
                    role_catalog,
                    candidate["metric_id"],
                    candidate["start_date"],
                    candidate["end_date"],
                    dialect="sqlite",
                    dimension=candidate.get("dimension"),
                    metric_version=requested_version,
                    role=case["role"],
                )
                sql = compiled["sql"]
                metric_version = compiled["metric_version"]
                fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                react_state = {
                    "data_source_id": "enterprise-ecommerce",
                    "tenant_id": "tenant-a",
                    "role": case["role"],
                    "region_id": case["region_id"],
                }
                trusted_plan = compiled.get("trusted_plan")
                if trusted_plan is None:
                    scoped_sql, _ = context_module.prepare_database_query(
                        sql, react_state, connector
                    )
                    result = execute_read_only_query(connector, scoped_sql)
                else:
                    with context_module.use_trusted_metric_plan(trusted_plan):
                        scoped_sql, _ = context_module.prepare_database_query(
                            sql, react_state, connector
                        )
                        result = execute_read_only_query(connector, scoped_sql)
                actual_status = "executed"
                actual_rows = result.rows
                returned_rows = len(actual_rows)
            except (KeyError, TypeError, ValueError, SQLQueryFailure):
                actual_status = "rejected"
                actual_rows = None

            expected_rows = case["expected"]
            passed = request_matches and actual_status == case["status"]
            if passed and expected_rows is not None:
                passed = _metric_rows_match(actual_rows, expected_rows)
            outcomes.append(
                {
                    "case": case_id,
                    "status": actual_status,
                    "passed": passed,
                    "metric_version": metric_version,
                    "query_sha256": fingerprint,
                    "returned_rows": returned_rows,
                }
            )
    finally:
        connection.close()
        if previous_mapping is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = previous_mapping

    count = len(outcomes)
    passed_count = sum(item["passed"] for item in outcomes)
    by_category, macro_average_pass_rate = _category_scorecard(
        outcomes, METRIC_CATEGORIES, "case"
    )
    return {
        "case_count": count,
        "passed": passed_count,
        "failed": count - passed_count,
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "rejected": sum(item["status"] == "rejected" for item in outcomes),
        "pass_rate": passed_count / count if count else 0,
        "by_category": by_category,
        "macro_average_pass_rate": macro_average_pass_rate,
        "cases": outcomes,
        "note": (
            "Fixed metric requests use the DB-GPT App compiler, schema/row policy, "
            "and read-only SQLite gateway; results are checked locally and omitted."
        ),
    }


def load_ambiguity_candidates(path: str | Path) -> dict[str, dict[str, object]]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError(
            "Ambiguity candidate JSON file exceeds the configured size cap"
        )
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(AMBIGUITY_EXPECTATIONS):
        raise ValueError("Ambiguity candidates must map known case IDs to actions")
    for candidate in raw.values():
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"action", "missing_fields"}
            or not isinstance(candidate["action"], str)
            or candidate["action"] not in {"clarify", "answer"}
            or not isinstance(candidate["missing_fields"], list)
            or any(
                not isinstance(field, str) or field not in AMBIGUITY_FIELDS
                for field in candidate["missing_fields"]
            )
            or len(set(candidate["missing_fields"])) != len(candidate["missing_fields"])
        ):
            raise ValueError(
                "Ambiguity actions must contain a valid action and field list"
            )
    return raw


def load_multiturn_authorization_candidates(path: str | Path) -> dict[str, list[str]]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError(
            "Multi-turn authorization candidate JSON file exceeds the "
            "configured size cap"
        )
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(AUTHORIZATION_CASES):
        raise ValueError(
            "Multi-turn authorization candidates must map known scenario IDs "
            "to SQL turns"
        )
    for sql_turns in raw.values():
        if (
            not isinstance(sql_turns, list)
            or len(sql_turns) > MAX_AUTHORIZATION_TURNS
            or any(
                not isinstance(sql, str) or len(sql) > MAX_SQL_LENGTH
                for sql in sql_turns
            )
        ):
            raise ValueError(
                "Multi-turn authorization candidates must contain bounded "
                "SQL turn lists"
            )
    return raw


def evaluate_ambiguity_candidates(
    candidates: Mapping[str, Mapping[str, object]],
) -> dict:
    """Score whether ambiguous prompts trigger clarification for the right fields."""
    outcomes = []
    for case_id, expected_fields in AMBIGUITY_EXPECTATIONS.items():
        candidate = candidates.get(case_id)
        if candidate is None:
            outcomes.append({"case": case_id, "status": "missing", "passed": False})
            continue
        fingerprint = hashlib.sha256(
            json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        passed = (
            candidate.get("action") == "clarify"
            and set(candidate.get("missing_fields", [])) == expected_fields
        )
        outcomes.append(
            {
                "case": case_id,
                "status": "correct" if passed else "incorrect",
                "passed": passed,
                "response_sha256": fingerprint,
            }
        )

    count = len(outcomes)
    passed = sum(item["passed"] for item in outcomes)
    return {
        "case_count": count,
        "correct": passed,
        "incorrect": sum(item["status"] == "incorrect" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "accuracy": passed / count if count else 0,
        "cases": outcomes,
        "note": (
            "Fixed ambiguity-action labels; not a live Agent clarification benchmark."
        ),
    }


def evaluate_multiturn_authorization_candidates(
    database_path: str | Path,
    candidates: Mapping[str, list[str]],
) -> dict:
    """Score multi-turn SQL using the same server-owned scope for each turn."""
    scenarios = []
    for case_id, case in AUTHORIZATION_CASES.items():
        sql_turns = candidates.get(case_id)
        expected_statuses = [turn["expected_status"] for turn in case["turns"]]
        if not isinstance(sql_turns, list):
            scenarios.append(
                {
                    "scenario": case_id,
                    "status": "missing",
                    "passed": False,
                    "turns": [],
                }
            )
            continue

        executor = tenant_executor(
            database_path,
            case["tenant_id"],
            region_id=case.get("region_id"),
        )
        turn_outcomes = []
        for index, expected_status in enumerate(expected_statuses):
            sql = sql_turns[index] if index < len(sql_turns) else None
            if not isinstance(sql, str) or not sql.strip():
                turn_outcomes.append(
                    {
                        "turn": index + 1,
                        "status": "missing",
                        "passed": False,
                    }
                )
                continue

            fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            try:
                actual = executor.run(sql)
            except QueryRejected:
                actual_status = "rejected"
            else:
                actual_status = (
                    "empty_result" if not actual["rows"] else "returned_rows"
                )
            turn_outcomes.append(
                {
                    "turn": index + 1,
                    "status": actual_status,
                    "passed": actual_status == expected_status,
                    "query_sha256": fingerprint,
                }
            )

        passed = len(sql_turns) == len(expected_statuses) and all(
            item["passed"] for item in turn_outcomes
        )
        scenarios.append(
            {
                "scenario": case_id,
                "status": "correct" if passed else "incorrect",
                "passed": passed,
                "extra_turns": max(0, len(sql_turns) - len(expected_statuses)),
                "turns": turn_outcomes,
            }
        )

    count = len(scenarios)
    passed = sum(item["passed"] for item in scenarios)
    return {
        "scenario_count": count,
        "passed": passed,
        "failed": count - passed,
        "missing": sum(item["status"] == "missing" for item in scenarios),
        "pass_rate": passed / count if count else 0,
        "scenarios": scenarios,
        "note": (
            "Fixed multi-turn SQL sequences keep tenant/region scope server-owned; "
            "not a live Agent authorization benchmark."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="Path for a new synthetic DB")
    parser.add_argument(
        "--candidates", required=True, help="JSON question-to-SQL mapping"
    )
    parser.add_argument(
        "--security-candidates",
        help="Optional JSON policy-denial and tenant-scope SQL mapping",
    )
    parser.add_argument(
        "--dialect-security-candidates",
        help="Optional PostgreSQL/MySQL AST security candidates (no DB connection)",
    )
    parser.add_argument(
        "--ambiguity-candidates",
        help="Optional JSON clarification-action mapping for ambiguous questions",
    )
    parser.add_argument(
        "--multiturn-authorization-candidates",
        help="Optional JSON SQL sequences for tenant/region authorization regressions",
    )
    parser.add_argument(
        "--schema-security-candidates",
        help="Optional SQL candidates for Schema metadata column-policy checks",
    )
    parser.add_argument(
        "--row-scope-candidates",
        help="Optional SQL candidates for ReAct tenant/region row-policy checks",
    )
    parser.add_argument(
        "--metric-candidates",
        help="Optional semantic metric requests for the DB-GPT App compiler scorecard",
    )
    parser.add_argument("--output", help="Write report JSON to this path")
    args = parser.parse_args()

    # Load and validate before creating the synthetic fixture DB.
    candidates = load_candidates(args.candidates)
    security_candidates = (
        load_security_candidates(args.security_candidates)
        if args.security_candidates
        else None
    )
    dialect_security_candidates = (
        load_dialect_security_candidates(args.dialect_security_candidates)
        if args.dialect_security_candidates
        else None
    )
    ambiguity_candidates = (
        load_ambiguity_candidates(args.ambiguity_candidates)
        if args.ambiguity_candidates
        else None
    )
    multiturn_authorization_candidates = (
        load_multiturn_authorization_candidates(args.multiturn_authorization_candidates)
        if args.multiturn_authorization_candidates
        else None
    )
    schema_security_candidates = (
        load_schema_security_candidates(args.schema_security_candidates)
        if args.schema_security_candidates
        else None
    )
    row_scope_candidates = (
        load_row_scope_candidates(args.row_scope_candidates)
        if args.row_scope_candidates
        else None
    )
    metric_candidates = (
        load_metric_candidates(args.metric_candidates)
        if args.metric_candidates
        else None
    )
    db = create_demo_database(args.database)
    executor = tenant_executor(db, "tenant-a")
    report = evaluate_candidates(executor, candidates)
    if security_candidates is not None:
        report["security"] = evaluate_security_candidates(executor, security_candidates)
    if dialect_security_candidates is not None:
        report["dialect_security"] = evaluate_dialect_security_candidates(
            dialect_security_candidates
        )
    if ambiguity_candidates is not None:
        report["ambiguity"] = evaluate_ambiguity_candidates(ambiguity_candidates)
    if multiturn_authorization_candidates is not None:
        report["multiturn_authorization"] = evaluate_multiturn_authorization_candidates(
            db, multiturn_authorization_candidates
        )
    if schema_security_candidates is not None:
        report["schema_security"] = evaluate_schema_security_candidates(
            schema_security_candidates
        )
    if row_scope_candidates is not None:
        report["row_scope"] = evaluate_row_scope_candidates(db, row_scope_candidates)
    if metric_candidates is not None:
        report["metrics"] = evaluate_metric_candidates(db, metric_candidates)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if (
        report["correct"] != report["question_count"]
        or ("security" in report and report["security"]["failed"])
        or ("dialect_security" in report and report["dialect_security"]["failed"])
        or ("ambiguity" in report and report["ambiguity"]["incorrect"])
        or (
            "multiturn_authorization" in report
            and report["multiturn_authorization"]["failed"]
        )
        or ("schema_security" in report and report["schema_security"]["failed"])
        or ("row_scope" in report and report["row_scope"]["failed"])
        or ("metrics" in report and report["metrics"]["failed"])
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
