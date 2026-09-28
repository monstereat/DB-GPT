# Live ReAct structured SQL result events

## Background and goal

- Background: The real-Agent gold evaluator expects `step.result` events containing bounded `sql_result` data. The ReAct `sql_query` tool currently returns only display chunks, so successful queries are counted as `missing_result`.
- Goal: Preserve the existing human-readable tool output and additionally attach a bounded, SQL-free result payload that the existing SSE serializer can emit.
- Success standard: A successful query produces an evaluator-compatible result event; failed or denied queries do not; the local Compose service runs the updated source and one live gold case is recognized.

## Scope

- Includes: normalize query results for JSON, add the structured payload to successful `sql_query` responses, add focused regression coverage, mount the tool source in the local Compose stack, and document the mount.
- Excludes: changing SQL policy, changing the expected result schema, altering prompts/model behavior, rebuilding the Docker image, or production database/identity configuration.

## User behavior

### AC-01: Successful query emits a bounded structured result

- Preconditions: a selected, authorized datasource executes a read-only SQL query successfully.
- Action: the Agent calls `sql_query`.
- Expected: the existing Markdown output remains, and the tool response includes columns, up to 50 JSON-safe rows, row count, and truncation state; the structured payload contains no SQL text.
- Verification: focused tool regression plus the existing bounded SSE serializer contract.

### AC-02: Failed and denied queries remain non-results

- Preconditions: SQL is denied or execution fails.
- Action: the Agent calls `sql_query`.
- Expected: the error payload is returned as before and no `sql_result` object is emitted.
- Verification: existing policy/error regressions and a structured-result absence assertion.

### AC-03: Local live evaluator observes the event

- Preconditions: local DB-GPT Compose is running with the synthetic approved datasource.
- Action: run a one-question gold evaluation.
- Expected: evaluator classifies the result as correct, incorrect, invalid, truncated, or rejected, never `missing_result` solely because the event was omitted.
- Verification: live API request and scorecard output.

## Boundaries and constraints

- Security/privacy: the query has already passed authorization and read-only enforcement; the event may contain only the same bounded result rows shown to the Agent, never raw SQL or driver exceptions.
- Compatibility: retain the existing `chunks` response and Markdown rendering; the SSE serializer remains the authority for the 128 KiB event cap.
- Performance: cap the event at 50 rows, matching the existing UI display limit.
- Existing project rules: Python/DB-GPT remains the primary backend; preserve unrelated worktree changes and update `docs/develop-me-roadmap.md` after verification.

## Assumptions

- The current local test datasource contains synthetic data and can be queried safely.
- The session-level authorization to complete the roadmap objective and verify it covers this evaluator contract fix.

## Approval

- Spec status: approved
- Approver: 主人（既有目标授权）
- Approval evidence: 用户授权“完成 DB-GPT docs/develop-me-roadmap.md 中当前未完成的任务……及候选 SQL 评测扩展；保持 Python/DB-GPT 作为主要后端，按仓库规则逐步实现、验证并同步路线图”，并要求不再为实现细节反复确认。
