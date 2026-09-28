# Plan: shared report template governance storage

1. Adapt `ReportTemplateReleaseStore` to SQLAlchemy Core with SQLite path/URL compatibility and PostgreSQL support; manage schema initialization in the store.
2. Add `DBGPT_REPORT_TEMPLATE_DATABASE_URL` and an explicit `create_app` injection point. Preserve the demo SQLite database default and keep task database configuration separate.
3. Make seed creation concurrency-safe and serialize review transitions with database row locks where supported; commit each review and audit event atomically.
4. Add SQLite regressions and isolated PostgreSQL tests for shared state, seed idempotency, approvals/rejections/self-review, and concurrent duplicate review.
5. Run focused and full offline suites, lint/format and diff checks; update roadmap and verification record with deployment limitations.
