import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from ecommerce_demo import (
    GOLD_ORDER_SENSITIVE,
    GOLD_QUERIES,
    GOLD_QUESTIONS,
    create_demo_database,
    gold_rows_match,
    tenant_executor,
)
from evaluate_candidates import (
    evaluate_ambiguity_candidates,
    evaluate_candidates,
    evaluate_dialect_security_candidates,
    evaluate_metric_candidates,
    evaluate_multiturn_authorization_candidates,
    evaluate_row_scope_candidates,
    evaluate_schema_security_candidates,
    evaluate_security_candidates,
    load_ambiguity_candidates,
    load_candidates,
    load_dialect_security_candidates,
    load_metric_candidates,
    load_multiturn_authorization_candidates,
    load_row_scope_candidates,
    load_schema_security_candidates,
    load_security_candidates,
)


@pytest.fixture
def guarded_db(tmp_path):
    db = create_demo_database(tmp_path / "ecommerce.sqlite")
    return tenant_executor(db, "tenant-a")


def test_gold_sql_candidates_score_all_correct(guarded_db):
    report = evaluate_candidates(guarded_db, GOLD_QUERIES)
    assert report["correct"] == len(GOLD_QUERIES)
    assert report["result_accuracy"] == 1.0
    assert report["incorrect"] == 0


def test_committed_50_question_bundle_scores_all_correct(guarded_db):
    candidates = load_candidates(Path(__file__).with_name("gold_candidates.json"))
    report = evaluate_candidates(guarded_db, candidates)
    assert len(candidates) == 50
    assert report["question_count"] == 50
    assert report["correct"] == 50
    assert report["result_accuracy"] == 1.0
    assert (
        sum(category["question_count"] for category in report["by_category"].values())
        == 50
    )
    assert report["macro_average_accuracy"] == 1.0


def test_gold_question_order_sensitivity_is_explicit_and_complete():
    assert len(GOLD_ORDER_SENSITIVE) == 50
    assert all(isinstance(item["order_sensitive"], bool) for item in GOLD_QUESTIONS)
    assert {
        question for question, ordered in GOLD_ORDER_SENSITIVE.items() if ordered
    } == {
        "q09",
        "q14",
        "q45",
        "q47",
    }


def test_unordered_candidate_accepts_same_rows_in_different_order(guarded_db):
    candidate = GOLD_QUERIES["q01"].replace(
        "ORDER BY sales_cents DESC", "ORDER BY region DESC"
    )
    report = evaluate_candidates(guarded_db, {"q01": candidate})

    assert report["cases"][0]["order_sensitive"] is False
    assert report["cases"][0]["status"] == "correct"


def test_top_three_candidate_requires_ranked_order(guarded_db):
    candidate = GOLD_QUERIES["q47"].replace(
        "ORDER BY sales_cents DESC,p.product_name", "ORDER BY p.product_name"
    )
    report = evaluate_candidates(guarded_db, {"q47": candidate})
    outcome = next(item for item in report["cases"] if item["question"] == "q47")

    assert outcome["order_sensitive"] is True
    assert outcome["status"] == "incorrect"


def test_unordered_row_comparison_preserves_duplicate_multiplicity():
    expected = [["Guangzhou", 45000], ["Shenzhen", 32000]]

    assert gold_rows_match("q01", expected[::-1], expected)
    assert not gold_rows_match("q01", [*expected, expected[0]], expected)


def test_candidate_scorecard_reports_category_regressions_and_missing(guarded_db):
    candidates = dict(GOLD_QUERIES)
    candidates["q01"] = "SELECT 1 AS wrong_result"
    candidates["q02"] = "SELECT internal_note FROM orders"
    candidates.pop("q03")

    report = evaluate_candidates(guarded_db, candidates)

    assert report["by_category"]["regional_sales"] == {
        "question_count": 10,
        "correct": 9,
        "incorrect": 1,
        "rejected": 0,
        "missing": 0,
        "accuracy": 9 / 10,
    }
    assert report["by_category"]["refunds"]["rejected"] == 1
    assert report["by_category"]["refunds"]["accuracy"] < 1
    assert report["by_category"]["order_counts"]["missing"] == 1
    assert (
        sum(category["question_count"] for category in report["by_category"].values())
        == report["question_count"]
    )
    assert report["macro_average_accuracy"] == pytest.approx(
        sum(category["accuracy"] for category in report["by_category"].values())
        / len(report["by_category"])
    )


def test_evaluation_denies_injection_without_query_leak(guarded_db):
    questions = list(GOLD_QUERIES)
    report = evaluate_candidates(
        guarded_db,
        {
            questions[0]: "SELECT internal_note FROM orders",
            questions[1]: GOLD_QUERIES[questions[1]],
            questions[2]: "SELECT 1 AS total",
        },
    )
    assert report["correct"] == 1
    assert report["rejected"] == 1
    assert report["incorrect"] == 1
    assert "internal_note" not in json.dumps(report)
    assert "query_sha256" in report["cases"][0]


def test_unanswered_questions_are_counted(guarded_db):
    report = evaluate_candidates(guarded_db, {})
    assert report["correct"] == 0
    assert report["missing"] == len(GOLD_QUERIES)


def test_candidate_file_disallows_unknown_question(tmp_path):
    file = tmp_path / "candidates.json"
    file.write_text('{"secret_data": "SELECT * FROM orders"}')
    with pytest.raises(ValueError, match="known question"):
        load_candidates(file)


def test_candidate_file_limits_input_size(tmp_path):
    file = tmp_path / "huge.json"
    file.write_text(" " * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="size cap"):
        load_candidates(file)


def test_committed_security_bundle_rejects_attacks_and_enforces_tenant_scope(
    guarded_db,
):
    guarded_db.timeout_ms = 250
    candidates = load_security_candidates(
        Path(__file__).with_name("security_candidates.json")
    )
    report = evaluate_security_candidates(guarded_db, candidates)

    assert report["case_count"] == 19
    assert report["passed"] == 19
    assert report["rejected"] == 18
    assert report["scope_filtered"] == 1
    assert report["pass_rate"] == 1.0
    assert (
        sum(category["case_count"] for category in report["by_category"].values())
        == report["case_count"]
    )
    assert report["macro_average_pass_rate"] == 1.0
    assert report["by_category"]["sensitive_data"]["case_count"] == 3
    rendered = json.dumps(report)
    assert "internal_note" not in rendered
    assert "tenant-b" not in rendered
    assert "sqlite_schema" not in rendered
    assert "PRAGMA" not in rendered


def test_security_evaluation_counts_a_policy_bypass_as_failure(guarded_db):
    candidates = load_security_candidates(
        Path(__file__).with_name("security_candidates.json")
    )
    candidates["sensitive_column"] = "SELECT order_id FROM orders"

    report = evaluate_security_candidates(guarded_db, candidates)

    assert report["failed"] == 1
    assert report["cases"][0]["status"] == "returned_rows"
    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["category"] == "sensitive_data"
    assert report["by_category"]["sensitive_data"]["failed"] == 1
    assert report["macro_average_pass_rate"] < 1.0


def test_security_candidate_file_disallows_unknown_case(tmp_path):
    file = tmp_path / "security.json"
    file.write_text('{"unknown": "SELECT 1"}')
    with pytest.raises(ValueError, match="known case IDs"):
        load_security_candidates(file)


def test_committed_schema_security_bundle_scores_ast_column_policy():
    candidates = load_schema_security_candidates(
        Path(__file__).with_name("schema_security_candidates.json")
    )

    report = evaluate_schema_security_candidates(candidates)

    assert report["case_count"] == 15
    assert report["passed"] == 15
    assert report["rejected"] == 12
    assert report["accepted"] == 3
    assert report["pass_rate"] == 1.0
    assert (
        sum(category["case_count"] for category in report["by_category"].values())
        == report["case_count"]
    )
    assert report["macro_average_pass_rate"] == 1.0
    assert report["by_category"]["sensitive_columns"]["case_count"] == 4
    rendered = json.dumps(report)
    assert "internal_cost_cents" not in rendered
    assert "tenant_id" not in rendered


def test_schema_security_evaluation_counts_a_policy_bypass_as_failure():
    candidates = load_schema_security_candidates(
        Path(__file__).with_name("schema_security_candidates.json")
    )
    candidates["confidential_column"] = "SELECT product_id FROM products"

    report = evaluate_schema_security_candidates(candidates)

    assert report["failed"] == 1
    assert report["cases"][0]["decision"] == "accepted"
    assert report["cases"][0]["category"] == "sensitive_columns"
    assert report["by_category"]["sensitive_columns"]["failed"] == 1
    assert report["macro_average_pass_rate"] < 1.0


@pytest.mark.parametrize(
    "payload",
    [
        '{"unknown": "SELECT 1"}',
        '{"confidential_column": ""}',
        '{"confidential_column": 12}',
    ],
)
def test_schema_security_candidate_loader_rejects_invalid_values(tmp_path, payload):
    file = tmp_path / "schema-security.json"
    file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_schema_security_candidates(file)


def test_committed_dialect_security_bundle_scores_postgres_and_mysql():
    candidates = load_dialect_security_candidates(
        Path(__file__).with_name("dialect_security_candidates.json")
    )

    report = evaluate_dialect_security_candidates(candidates)

    assert report["dialect_count"] == 2
    assert report["case_count"] == 20
    assert report["passed"] == 20
    assert report["failed"] == 0
    assert report["dialects"]["postgresql"]["accepted"] == 1
    assert report["dialects"]["postgresql"]["rejected"] == 9
    assert report["dialects"]["mysql"]["accepted"] == 1
    assert report["dialects"]["mysql"]["rejected"] == 9
    assert report["macro_average_pass_rate"] == 1.0
    assert report["by_category"]["server_file_access"] == {
        "case_count": 2,
        "passed": 2,
        "failed": 0,
        "pass_rate": 1.0,
    }
    assert (
        report["dialects"]["postgresql"]["by_category"]["session_side_effects"][
            "case_count"
        ]
        == 3
    )
    assert (
        report["dialects"]["mysql"]["by_category"]["session_side_effects"]["case_count"]
        == 2
    )
    rendered = json.dumps(report)
    assert "pg_read_file" not in rendered
    assert "OUTFILE" not in rendered
    assert "/etc/passwd" not in rendered


def test_dialect_security_evaluation_catches_parser_policy_bypass():
    candidates = load_dialect_security_candidates(
        Path(__file__).with_name("dialect_security_candidates.json")
    )
    candidates["postgresql"]["server_file_read"] = "SELECT order_id FROM orders"

    report = evaluate_dialect_security_candidates(candidates)

    assert report["failed"] == 1
    assert report["pass_rate"] == 0.95
    file_access = report["dialects"]["postgresql"]["by_category"]["server_file_access"]
    assert file_access["case_count"] == 1
    assert file_access["passed"] == 0
    assert file_access["pass_rate"] == 0
    failed = next(
        case
        for case in report["dialects"]["postgresql"]["cases"]
        if case["case"] == "server_file_read"
    )
    assert failed["decision"] == "accepted"


@pytest.mark.parametrize(
    "payload",
    [
        '{"sqlite": {"read_only_select": "SELECT 1"}}',
        '{"postgresql": {"unknown": "SELECT 1"}, "mysql": {}}',
        '{"postgresql": {"read_only_select": ""}, "mysql": {}}',
    ],
)
def test_dialect_security_candidate_loader_rejects_invalid_shape(tmp_path, payload):
    file = tmp_path / "dialect-security.json"
    file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_dialect_security_candidates(file)


def test_committed_ambiguity_bundle_scores_clarification_action_and_fields():
    candidates = load_ambiguity_candidates(
        Path(__file__).with_name("ambiguity_candidates.json")
    )

    report = evaluate_ambiguity_candidates(candidates)

    assert report["case_count"] == 6
    assert report["correct"] == 6
    assert report["incorrect"] == 0
    assert report["accuracy"] == 1.0


@pytest.mark.parametrize(
    "payload",
    [
        '{"unknown": {"action": "clarify", "missing_fields": []}}',
        '{"a01": {"action": "clarify", "missing_fields": ["metric", "metric"]}}',
        '{"a01": {"action": "clarify", "missing_fields": ["tenant_id"]}}',
        '{"a01": {"action": "answer", "missing_fields": [], "sql": "SELECT 1"}}',
    ],
)
def test_ambiguity_candidate_file_rejects_unknown_or_malformed_values(
    tmp_path, payload
):
    file = tmp_path / "ambiguity.json"
    file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_ambiguity_candidates(file)


def test_premature_answer_is_scored_incorrect():
    report = evaluate_ambiguity_candidates(
        {"a01": {"action": "answer", "missing_fields": []}}
    )

    assert report["incorrect"] == 1
    assert report["missing"] == 5
    assert report["cases"][0]["status"] == "incorrect"


def test_committed_multiturn_authorization_bundle_preserves_server_scope(tmp_path):
    database = create_demo_database(tmp_path / "multiturn-ecommerce.sqlite")
    candidates = load_multiturn_authorization_candidates(
        Path(__file__).with_name("multiturn_authorization_candidates.json")
    )

    report = evaluate_multiturn_authorization_candidates(database, candidates)

    assert report["scenario_count"] == 3
    assert report["passed"] == 3
    assert report["failed"] == 0
    assert report["pass_rate"] == 1.0
    assert report["scenarios"][0]["turns"][1]["status"] == "rejected"
    assert report["scenarios"][1]["turns"][1]["status"] == "empty_result"
    assert "tenant-b" not in json.dumps(report)
    assert "region_id = 'b-gz'" not in json.dumps(report)


def test_multiturn_authorization_evaluation_catches_scope_bypass(tmp_path):
    database = create_demo_database(tmp_path / "multiturn-ecommerce.sqlite")
    candidates = load_multiturn_authorization_candidates(
        Path(__file__).with_name("multiturn_authorization_candidates.json")
    )
    candidates["tenant_switch_after_followup"][1] = (
        "SELECT order_id FROM orders ORDER BY order_id"
    )

    report = evaluate_multiturn_authorization_candidates(database, candidates)

    assert report["failed"] == 1
    assert report["scenarios"][0]["turns"][1]["status"] == "returned_rows"
    assert report["scenarios"][0]["turns"][1]["passed"] is False


@pytest.mark.parametrize(
    "payload",
    [
        '{"unknown": ["SELECT 1"]}',
        '{"tenant_switch_after_followup": "SELECT 1"}',
        '{"tenant_switch_after_followup": ["SELECT 1", 1]}',
    ],
)
def test_multiturn_authorization_candidate_loader_validates_shape(tmp_path, payload):
    file = tmp_path / "multiturn-candidates.json"
    file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_multiturn_authorization_candidates(file)


def test_committed_row_scope_bundle_scores_react_tenant_and_region_policies(tmp_path):
    database = create_demo_database(tmp_path / "row-scope-ecommerce.sqlite")
    candidates = load_row_scope_candidates(
        Path(__file__).with_name("row_scope_candidates.json")
    )

    report = evaluate_row_scope_candidates(database, candidates)

    assert report["case_count"] == 11
    assert report["passed"] == 11, [
        case for case in report["cases"] if not case["passed"]
    ]
    assert report["failed"] == 0
    assert report["rejected"] == 4
    assert report["pass_rate"] == 1.0
    assert (
        sum(category["case_count"] for category in report["by_category"].values())
        == report["case_count"]
    )
    assert report["macro_average_pass_rate"] == 1.0
    assert report["by_category"]["region_scope"]["case_count"] == 4
    rendered = json.dumps(report)
    assert "tenant-b" not in rendered
    assert "a-gz" not in rendered
    assert "order_id" not in rendered
    assert "query_sha256" in rendered


def test_row_scope_evaluation_catches_tenant_and_region_policy_bypasses(
    tmp_path, monkeypatch
):
    database = create_demo_database(tmp_path / "row-scope-bypass.sqlite")
    candidates = load_row_scope_candidates(
        Path(__file__).with_name("row_scope_candidates.json")
    )
    candidates["tenant_or_bypass"] = (
        "SELECT order_id FROM orders WHERE tenant_id = 'tenant-b' OR 1 = 1"
    )
    candidates["region_or_bypass"] = (
        "SELECT order_id FROM orders WHERE region_id = 'a-sz' OR 1 = 1"
    )
    app_source = Path(__file__).resolve().parents[2] / "packages/dbgpt-app/src"
    sys.path.insert(0, str(app_source))
    policy_module = importlib.import_module("dbgpt_app.openapi.api_v1.business_context")
    monkeypatch.setattr(
        policy_module, "apply_database_row_scope", lambda sql, *args, **kwargs: sql
    )

    report = evaluate_row_scope_candidates(database, candidates)

    failed_cases = {
        case["case"]: case for case in report["cases"] if not case["passed"]
    }
    assert failed_cases["tenant_or_bypass"]["returned_rows"] == 9
    assert failed_cases["region_or_bypass"]["returned_rows"] == 9
    assert report["by_category"]["bypass_resistance"]["failed"] == 2
    assert report["macro_average_pass_rate"] < 1.0


@pytest.mark.parametrize(
    "payload",
    [
        '{"unknown": "SELECT 1"}',
        '{"tenant_scope": ""}',
        '{"tenant_scope": 12}',
    ],
)
def test_row_scope_candidate_loader_rejects_unknown_or_invalid_values(
    tmp_path, payload
):
    file = tmp_path / "row-scope-candidates.json"
    file.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        load_row_scope_candidates(file)


def test_committed_metric_bundle_uses_app_compiler_and_scoped_execution(tmp_path):
    db = create_demo_database(tmp_path / "metric-ecommerce.sqlite")
    candidates = load_metric_candidates(
        Path(__file__).with_name("metric_candidates.json")
    )

    report = evaluate_metric_candidates(db, candidates)

    assert report["case_count"] == 11
    assert report["passed"] == 11
    assert report["failed"] == 0
    assert report["rejected"] == 1
    assert report["pass_rate"] == 1.0
    assert (
        sum(category["case_count"] for category in report["by_category"].values())
        == report["case_count"]
    )
    assert report["macro_average_pass_rate"] == 1.0
    assert report["by_category"]["time_and_version_semantics"]["case_count"] == 6
    assert report["cases"][1]["metric_version"] == "1.0.0"
    assert report["cases"][2]["metric_version"] == "2.0.0"
    assert report["cases"][8]["status"] == "executed"
    assert report["cases"][9]["status"] == "rejected"
    assert report["cases"][9]["query_sha256"] is None
    assert report["cases"][9]["metric_version"] is None
    assert report["cases"][10]["returned_rows"] == 1
    rendered = json.dumps(report)
    for sensitive_value in (
        "tenant-a",
        "a-gz",
        "internal_cost_cents",
        "Guangzhou",
        "77000",
        "43.12",
    ):
        assert sensitive_value not in rendered


def test_metric_candidate_scorecard_exposes_authorization_category_regression(
    tmp_path,
):
    db = create_demo_database(tmp_path / "metric-authorization-regression.sqlite")
    candidates = load_metric_candidates(
        Path(__file__).with_name("metric_candidates.json")
    )
    candidates["gross_margin_non_admin"]["metric_id"] = "sales_amount"

    report = evaluate_metric_candidates(db, candidates)

    assert report["failed"] == 1
    assert report["cases"][9]["category"] == "role_authorization"
    assert report["by_category"]["role_authorization"]["failed"] == 1
    assert report["macro_average_pass_rate"] < 1.0


@pytest.mark.parametrize(
    "payload",
    [
        {
            "unknown": {
                "metric_id": "sales_amount",
                "start_date": "2026-04-01",
                "end_date": "2026-07-01",
            }
        },
        {
            "sales_q2": {
                "metric_id": "sales_amount",
                "start_date": "2026-04-01",
                "end_date": "2026-07-01",
                "role": "admin",
            }
        },
        {
            "sales_q2": {
                "metric_id": 12,
                "start_date": "2026-04-01",
                "end_date": "2026-07-01",
            }
        },
    ],
)
def test_metric_candidate_loader_rejects_unknown_fields_and_values(tmp_path, payload):
    file = tmp_path / "metric-candidates.json"
    file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_metric_candidates(file)


def test_cli_runs_all_bundles_without_leaking_candidates(tmp_path):
    example_dir = Path(__file__).parent
    report_path = tmp_path / "scorecard.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(example_dir / "evaluate_candidates.py"),
            "--database",
            str(tmp_path / "cli-ecommerce.sqlite"),
            "--candidates",
            str(example_dir / "gold_candidates.json"),
            "--security-candidates",
            str(example_dir / "security_candidates.json"),
            "--dialect-security-candidates",
            str(example_dir / "dialect_security_candidates.json"),
            "--ambiguity-candidates",
            str(example_dir / "ambiguity_candidates.json"),
            "--multiturn-authorization-candidates",
            str(example_dir / "multiturn_authorization_candidates.json"),
            "--schema-security-candidates",
            str(example_dir / "schema_security_candidates.json"),
            "--row-scope-candidates",
            str(example_dir / "row_scope_candidates.json"),
            "--metric-candidates",
            str(example_dir / "metric_candidates.json"),
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["correct"] == 50
    assert report["security"]["case_count"] == 19
    assert report["security"]["passed"] == 19
    assert report["security"]["rejected"] == 18
    assert report["security"]["scope_filtered"] == 1
    assert report["security"]["macro_average_pass_rate"] == 1.0
    assert report["dialect_security"]["case_count"] == 20
    assert report["dialect_security"]["passed"] == 20
    assert report["dialect_security"]["failed"] == 0
    assert report["ambiguity"]["case_count"] == 6
    assert report["ambiguity"]["correct"] == 6
    assert report["ambiguity"]["incorrect"] == 0
    assert report["multiturn_authorization"]["scenario_count"] == 3
    assert report["multiturn_authorization"]["passed"] == 3
    assert report["multiturn_authorization"]["failed"] == 0
    assert report["schema_security"]["case_count"] == 15
    assert report["schema_security"]["passed"] == 15
    assert report["schema_security"]["failed"] == 0
    assert report["schema_security"]["macro_average_pass_rate"] == 1.0
    assert report["row_scope"]["case_count"] == 11
    assert report["row_scope"]["passed"] == 11
    assert report["row_scope"]["failed"] == 0
    assert report["row_scope"]["macro_average_pass_rate"] == 1.0
    assert report["metrics"]["case_count"] == 11
    assert report["metrics"]["passed"] == 11
    assert report["metrics"]["failed"] == 0
    assert report["metrics"]["macro_average_pass_rate"] == 1.0
    assert report_text.strip() == completed.stdout.strip()

    raw_candidate_queries = [
        *load_candidates(example_dir / "gold_candidates.json").values(),
        *load_security_candidates(example_dir / "security_candidates.json").values(),
        *load_schema_security_candidates(
            example_dir / "schema_security_candidates.json"
        ).values(),
        *load_row_scope_candidates(example_dir / "row_scope_candidates.json").values(),
    ]
    raw_multiturn_sql = [
        sql
        for turns in load_multiturn_authorization_candidates(
            example_dir / "multiturn_authorization_candidates.json"
        ).values()
        for sql in turns
    ]
    raw_dialect_sql = [
        sql
        for candidates in load_dialect_security_candidates(
            example_dir / "dialect_security_candidates.json"
        ).values()
        for sql in candidates.values()
    ]
    for sql in raw_candidate_queries:
        assert sql not in report_text
    for sensitive_value in (
        "tenant-b",
        "internal_note",
        "secret-a",
        "PRAGMA table_info",
        "internal_cost_cents",
        "Guangzhou",
        "77000",
    ):
        assert sensitive_value not in report_text
    assert "最近经营情况怎么样" not in report_text
    assert "comparison_basis" not in report_text
    assert "列出当前租户的订单" not in report_text
    assert "切换到 b-gz 区域查询订单" not in report_text
    for sql in raw_multiturn_sql:
        assert sql not in report_text
    for sql in raw_dialect_sql:
        assert sql not in report_text
