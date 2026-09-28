# Spec 020: Stop ReAct on terminal SQL errors

## Problem

The SQL tool returns structured policy and execution failures as JSON. The ReAct action layer treated that JSON as a successful observation, allowing additional model calls after a permanent refusal or exhausted correction budget. A later model response could be slow or claim success despite the failed query.

## Scope

- Detect only `sql_query` observations with a structured `error.retryable` value of `false`.
- Mark that ReAct action failed, disable retry, and terminate the current agent loop.
- Preserve the failed tool step in the API event stream and return its safe server-owned message as the final response.
- Mount the changed Core action module read-only in the local test Compose service so the running service uses the verified implementation.

## Out of scope

- Changing SQL policy, correction-budget thresholds, datasource permissions, or model prompts.
- Claiming generic Text-to-SQL quality or production identity/database validation.

## Acceptance criteria

- AC-01: A structured non-retryable SQL error terminates ReAct with `is_exe_success=false` and `have_retry=false`.
- AC-02: Retryable SQL errors, non-SQL tools, and malformed observations do not trigger this terminal path.
- AC-03: The API displays the SQL error step and returns the safe structured error message, not a model-generated answer.
- AC-04: Focused Core/API tests pass and a local Agent request against the synthetic datasource confirms a single SQL tool call on sensitive-column denial.
