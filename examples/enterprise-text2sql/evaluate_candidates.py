"""Reproducible guarded Text-to-SQL candidate evaluation for the ecommerce MVP.

This evaluates supplied SQL, NOT an LLM's ability to write it. All SQL still
passes through GuardedSQLiteQuery with a server-owned tenant/column scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

from ecommerce_demo import (
    EXPECTED_TENANT_A, GOLD_QUERIES, create_demo_database, tenant_executor,
)
from guarded_query import GuardedSQLiteQuery, QueryRejected

MAX_CANDIDATES_BYTES = 256 * 1024
MAX_SQL_LENGTH = 10000


def evaluate_candidates(
    executor: GuardedSQLiteQuery, candidates: Mapping[str, str],
    expected: Mapping[str, dict] = EXPECTED_TENANT_A,
) -> dict:
    """Return a deterministic scorecard without echoing SQL or data values.

    The expected dataset must match the server-side executor's tenant. Model-
    generated SQL and question IDs are untrusted input; neither can set ACL.
    """
    outcomes = []
    for question in GOLD_QUERIES:
        sql = candidates.get(question)
        if not isinstance(sql, str) or not sql.strip():
            outcomes.append({"question": question, "status": "missing", "passed": False})
            continue
        if len(sql) > MAX_SQL_LENGTH:
            outcomes.append({"question": question, "status": "rejected", "passed": False})
            continue

        fingerprint = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        try:
            actual = executor.run(sql)
        except QueryRejected:
            outcomes.append({
                "question": question, "status": "rejected", "passed": False,
                "query_sha256": fingerprint,
            })
            continue

        passed = actual["columns"] == expected[question]["columns"] and (
            actual["rows"] == expected[question]["rows"]
        )
        outcomes.append({
            "question": question,
            "status": "correct" if passed else "incorrect",
            "passed": passed,
            "query_sha256": fingerprint,
            "duration_ms": actual["duration_ms"],
            "returned_rows": actual["returned_rows"],
        })

    count = len(outcomes)
    correct = sum(item["passed"] for item in outcomes)
    return {
        "question_count": count,
        "correct": correct,
        "incorrect": sum(item["status"] == "incorrect" for item in outcomes),
        "rejected": sum(item["status"] == "rejected" for item in outcomes),
        "missing": sum(item["status"] == "missing" for item in outcomes),
        "result_accuracy": correct / count if count else 0,
        "cases": outcomes,
        "note": "Guarded result equality on fixed synthetic data; not a live model benchmark.",
    }


def load_candidates(path: str | Path) -> dict[str, str]:
    file = Path(path)
    if file.stat().st_size > MAX_CANDIDATES_BYTES:
        raise ValueError("Candidate JSON file exceeds the configured size cap")
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) - set(GOLD_QUERIES):
        raise ValueError("Candidates must map known question IDs to SQL strings")
    if any(not isinstance(value, str) or len(value) > MAX_SQL_LENGTH
           for value in raw.values()):
        raise ValueError("Candidate SQL values must be strings within the size limit")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, help="Path for a new synthetic DB")
    parser.add_argument("--candidates", required=True, help="JSON question-to-SQL mapping")
    parser.add_argument("--output", help="Write report JSON to this path")
    args = parser.parse_args()

    # Load and validate before creating the synthetic fixture DB.
    candidates = load_candidates(args.candidates)
    db = create_demo_database(args.database)
    report = evaluate_candidates(tenant_executor(db, "tenant-a"), candidates)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["correct"] != report["question_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
