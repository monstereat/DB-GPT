# Tasks: shared report template governance storage

## T001: Add cross-dialect shared template store

- Acceptance criteria: SQLite path/URL compatibility, explicit PostgreSQL URL support, store-managed schema, concurrent seed safety, and atomic release/audit transactions.
- Status: complete

## T002: Wire explicit template database configuration

- Acceptance criteria: `DBGPT_REPORT_TEMPLATE_DATABASE_URL` or explicit app injection configures the template store; task database URL is never implicitly reused; local demo defaults remain compatible.
- Status: complete

## T003: Verify shared storage behavior

- Acceptance criteria: tests cover independent stores, seed idempotency, publish/reject/self-review, and duplicate concurrent reviews on SQLite and isolated PostgreSQL where available.
- Status: complete

## T004: Record verification and roadmap status

- Acceptance criteria: verification commands/results and remaining deployment requirements are recorded in `verify.md` and `docs/develop-me-roadmap.md`.
- Status: complete
