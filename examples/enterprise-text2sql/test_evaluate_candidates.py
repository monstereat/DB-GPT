import json
import pytest

from ecommerce_demo import GOLD_QUERIES, create_demo_database, tenant_executor
from evaluate_candidates import evaluate_candidates, load_candidates


@pytest.fixture
def guarded_db(tmp_path):
    db = create_demo_database(tmp_path / "ecommerce.sqlite")
    return tenant_executor(db, "tenant-a")


def test_gold_sql_candidates_score_all_correct(guarded_db):
    report = evaluate_candidates(guarded_db, GOLD_QUERIES)
    assert report["correct"] == len(GOLD_QUERIES)
    assert report["result_accuracy"] == 1.0
    assert report["incorrect"] == 0


def test_evaluation_denies_injection_without_query_leak(guarded_db):
    questions = list(GOLD_QUERIES)
    report = evaluate_candidates(guarded_db, {
        questions[0]: "SELECT internal_note FROM orders",
        questions[1]: GOLD_QUERIES[questions[1]],
        questions[2]: "SELECT 1 AS total",
    })
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
