# Verification: shared report template governance storage

## Automated checks

- Full enterprise Text-to-SQL offline suite: `198 passed, 2 skipped`.
- Full enterprise Text-to-SQL suite with the isolated PostgreSQL test enabled: `199 passed, 1 skipped`.
- Isolated PostgreSQL 16.6 template-store regressions: `9 passed`. The test used a temporary schema and covered two concurrent store initializers, idempotent seed/audit rows, shared submissions, approval/rejection, self-review denial, concurrent duplicate approval, and append-only audit enforcement.
- Ruff format/check passed for `report_template_governance.py`, `api.py`, and `test_report_template_governance.py`.
- Python `compileall` passed for those Python files.
- `git diff --check` passed for the implementation, test, documentation, and spec files.
- The standalone focused SQLite template governance run passed with the PostgreSQL test skipped.

## Configuration

- `DBGPT_REPORT_TEMPLATE_DATABASE_URL` selects the shared template store. SQLite path and URL behavior remain available for local use.
- `DBGPT_REPORT_TASK_DATABASE_URL` remains independent and is not used as a template-store fallback.
- The local PostgreSQL test container `codex-template-governance-pg-test` was removed after verification.

## Remaining deployment work

The isolated database test does not verify target-environment grants, TLS, backups, restore procedures, or production failure recovery. Deployments must install the matching SQLAlchemy PostgreSQL driver and provide credentials through the deployment secret manager. No DB-GPT Serve metadata schema migration was made.
