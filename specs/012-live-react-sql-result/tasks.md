# Tasks: Live ReAct structured SQL result events

## T001: Emit bounded structured results from successful SQL tool calls

- Dependencies: none.
- Allowed files: `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py`, `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_sql_query.py`, `docker/compose_examples/develop-me-test/compose.yaml`, `docker/compose_examples/develop-me-test/README.md`, `specs/012-live-react-sql-result/**`.
- Actions: Preserve Markdown chunks; add JSON-safe bounded result fields only after successful query execution; cover successful and denied/failed tool responses; mount the source file read-only and document it.
- Acceptance criteria: AC-01, AC-02.
- Verification commands:
  1. `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_sql_query.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_sql_result_events.py`
  2. `.venv/bin/python -m py_compile packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py`
  3. `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet`
- Scope baseline: `specs/012-live-react-sql-result/scope-baseline-T001.json`.
- Scope report: `specs/012-live-react-sql-result/scope-report-T001.json`.
- Completion: all registered checks pass and T001 scope gate passes.
- Status: done.
- Evidence IDs: `T001-unit`, `T001-syntax`, `T001-compose`.
- Evidence: focused SQL tool and SSE serializer suite `18 passed`; py_compile passed; Compose config validation passed.

## T002: Apply source mount, score the live dataset, and record results

- Dependencies: T001.
- Allowed files: `docs/develop-me-roadmap.md`, `specs/012-live-react-sql-result/**`.
- Actions: Recreate only the project-owned DB-GPT service; run one-case and full 50-case gold evaluations; preserve the redacted full scorecard in `evidence/`; update roadmap evidence and remaining model limitations.
- Acceptance criteria: AC-03.
- Verification commands:
-  1. `DBGPT_EVAL_ACCESS_TOKEN=local-demo-only-not-a-credential DBGPT_AGENT_API_URL=http://127.0.0.1:5671 DBGPT_AGENT_DATABASE=ecommerce-demo .venv/bin/python examples/enterprise-text2sql/evaluate_agent.py --dataset /tmp/dbgpt-agent-q01.json --timeout 120 > /tmp/dbgpt-agent-q01-scorecard.json; status=$?; test "$status" -eq 0 -o "$status" -eq 1`
-  2. `.venv/bin/python -c 'import json; d=json.load(open("/tmp/dbgpt-agent-q01-scorecard.json")); assert d["question_count"] == 1 and d["missing_result"] == 0; print(d["result_accuracy"], d["cases"])'`
-  3. `DBGPT_EVAL_ACCESS_TOKEN=local-demo-only-not-a-credential DBGPT_AGENT_API_URL=http://127.0.0.1:5671 DBGPT_AGENT_DATABASE=ecommerce-demo .venv/bin/python examples/enterprise-text2sql/evaluate_agent.py --timeout 120 > specs/012-live-react-sql-result/evidence/live-gold-scorecard.json; status=$?; test "$status" -eq 0 -o "$status" -eq 1`
-  4. `.venv/bin/python -c 'import json; d=json.load(open("specs/012-live-react-sql-result/evidence/live-gold-scorecard.json")); assert d["question_count"] == 50; print(d["result_accuracy"], d["correct"], d["missing_result"], d["invalid_result"], d["truncated"])'`
- Scope baseline: `specs/012-live-react-sql-result/scope-baseline-T002.json`.
- Scope report: `specs/012-live-react-sql-result/scope-report-T002.json`.
- Completion: live single-case scorecard contains a structured SQL result; full scorecard contains 50 cases and its actual outcomes are recorded without claiming perfect model accuracy; T002 scope gate passes.
- Status: done.
- Evidence IDs: `T002-live-smoke-retry1`, `T002-live-result-retry1`, `T002-live-gold`, `T002-scorecard`.
- Evidence: one-question live scorecard recognized a structured SQL result (`missing_result=0`, `incorrect`); full 50-question run completed with 0 correct, 30 incorrect, 20 missing, 0 invalid, and 0 truncated results. This verifies result-event plumbing and measures model quality; it does not pass the model accuracy bar.
