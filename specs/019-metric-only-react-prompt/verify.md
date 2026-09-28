# Verification report

## Result

Ready for user review. The DB-GPT screenshot question now returns the exact expected structured regional sales result in the local Docker test stack.

## Acceptance criteria

- **AC-01 — Pass.** Prompt regression verifies the metric-only form calls `metric_query` with the published metric arguments, has no `sql_query` action, and retains the generic SQL action in normal database mode.
- **AC-02 — Pass.** Focused prompt, lifecycle, and metric compiler suite: **20 passed**, 3 pre-existing dependency deprecation warnings.
- **AC-03 — Pass.** Live q01 scorecard: **1/1 correct**, zero incorrect/missing/invalid/truncated. Structured columns are `region`, `sales_cents`; rows match Guangzhou 45,000 and Shenzhen 32,000 cents. Evidence: `evidence/q01-scorecard.json`.

## Runtime and safety checks

- Local DB-GPT Compose service is healthy at `http://127.0.0.1:5671/api/health`; the Ollama and DB-GPT containers are healthy.
- The demo metric catalog and changed Python sources are mounted read-only; no database schema or fixture data was changed.
- Compiled region joins now bind tenant and region IDs together; refund-to-order joins bind tenant and order IDs together. Unit tests verify these joins and the completed-order filter.
- `git diff --check` passed.

## Limitations

- This proves the single screenshot question on synthetic demo data. The historical 50-question scorecard remains 0/50 and was not rerun; general-purpose SQL generation still needs work.
- Building a separate test image failed at Ubuntu APT signature verification; signature checks were not bypassed. The local stack uses read-only source/catalog mounts, so the running test service has the verified changes.
- This is a local development identity and synthetic datasource, not production OIDC/RLS validation.
