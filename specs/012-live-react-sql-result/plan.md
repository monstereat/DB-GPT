# Implementation plan: Live ReAct structured SQL result events

## Confirmed context

- `sql_query()` executes the authorized, read-only request and returns only `chunks`; `agentic_data_api.emit_tool_chunks()` emits `step.result` only when a tool response contains a validated `result` object.
- `serialize_sql_result_event()` already enforces the existing `sql_result` schema, 50-row bound, and 128 KiB event cap, and strips non-contract fields.
- The local Compose stack mounts `agentic_data_api.py` but not `tools/sql_query.py`; source changes to the tool would otherwise not be live without rebuilding the space-constrained image.
- `evaluate_agent.py` returns exit code 1 for an imperfect score, so the full-scorecard evidence command must accept only exit codes 0 or 1 while still allowing transport/configuration failures to fail.

## Approach

- Keep the current Markdown chunk for the model and UI. On successful execution, add a sibling `result` object with JSON-safe columns and at most the first 50 rows, the observed row count, and truncation state.
- Convert non-JSON-native values conservatively for event transport (dates via `isoformat`; unsupported values to strings) without modifying the Markdown representation.
- Do not add a structured result on empty, denied, or failed-query paths.
- Add a read-only host bind mount for `sql_query.py`; document the local live evaluator command and the source mount.
- First run focused tests, syntax, and Compose validation; recreate only the project-owned DB-GPT service; verify one gold case; then run the full 50-question gold scorecard and store only its existing redacted statuses/hashes.

## File list

| File | Operation | Reason | Acceptance |
| --- | --- | --- | --- |
| `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py` | modify | Attach bounded structured result to successful SQL output | AC-01, AC-02 |
| `packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_sql_query.py` | modify | Lock down success/error payload contract | AC-01, AC-02 |
| `docker/compose_examples/develop-me-test/compose.yaml` | modify | Mount the updated tool source in the running test service | AC-03 |
| `docker/compose_examples/develop-me-test/README.md` | modify | Explain source mount and local evaluation invocation | AC-03 |
| `docs/develop-me-roadmap.md` | modify | Record full live scorecard evidence and remaining model limitations | AC-03 |
| `specs/012-live-react-sql-result/**` | add/modify | Preserve change, state, test and scorecard evidence | AC-01–AC-03 |

## Execution order

1. Implement result serialization in `sql_query`, add focused success/failure coverage, and add the Compose bind mount/docs.
2. Run focused tests, Python syntax checks, and Compose config validation.
3. Recreate the project-owned DB-GPT container to apply the new source mount; verify one-question SSE/live scorecard behavior.
4. Run the full 50-case Agent gold evaluator; record a redacted scorecard summary and update roadmap checkboxes only where the evidence supports it.

## Verification plan

| Layer | Command or action | Passing condition |
| --- | --- | --- |
| Unit | `PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-app/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/tests/test_sql_query.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_sql_result_events.py` | Focused SQL tool and serializer regressions pass |
| Syntax | `.venv/bin/python -m py_compile packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tools/sql_query.py` | Exit code 0 |
| Compose | `docker compose -p dbgpt-develop-me-test -f docker/compose_examples/develop-me-test/compose.yaml config --quiet` | Exit code 0 |
| Live | Full `evaluate_agent.py` gold dataset against `http://127.0.0.1:5671` and `ecommerce-demo` | 50 statuses emitted; no case is `missing_result` due to absent SSE payload; report actual accuracy without requiring 100% |

## Execution control

- State recovery: on
- Independent review: off
- Branch strategy: current `develop-me` branch
- Commit strategy: none

## State registration

- Acceptance criteria: AC-01, AC-02, AC-03
- Tasks: T001, T002
- State file: `specs/012-live-react-sql-result/state.json`

## Risks and rollback

- The SSE result duplicates up to 50 rows already returned as Markdown, increasing payload size; the existing serializer rejects payloads over 128 KiB and safely omits oversized events.
- A low-parameter local model can still produce incorrect SQL or fail to terminate. This should be reported as model accuracy/latency, not as successful evaluator output.
- Rollback: remove the added bind mount and revert only the focused structured-result implementation if live output violates the existing contract; preserve the pre-existing worktree.

## Approval

- Plan status: approved
- Approver: 主人（既有目标授权）
- Approval evidence: 用户已授权完整完成 roadmap 未完成任务、验证并维护路线图，并明确表示无需逐项确认实现选择。
