# Shared report template governance storage

## Goal

Allow multiple API instances to share report-template submissions, reviews, published catalogs, and audit events through an explicitly configured SQLAlchemy database URL, while preserving the local SQLite demo default.

## Scope

- Keep SQLite path and SQLite URL compatibility for the demo and tests.
- Add the explicit `DBGPT_REPORT_TEMPLATE_DATABASE_URL` configuration; do not implicitly reuse the report-task database URL.
- Support PostgreSQL with store-managed cross-dialect schema initialization; do not alter DB-GPT Serve metadata schema.
- Keep template release state changes and append-only audit events in one transaction.
- Serialize concurrent reviews so only one reviewer can transition a pending release.
- Make initial seed insertion safe when multiple store instances initialize the same database concurrently.

## Acceptance criteria

- Existing SQLite path behavior and API defaults remain compatible.
- A configured SQLAlchemy URL is passed only to the template store; report-task storage configuration remains independent.
- Two stores connected to one database observe the same seed, submissions, review outcomes, published snapshot, and audit history.
- Seed initialization is idempotent under sequential and concurrent store initialization.
- Approval, rejection, and self-review denial are audited consistently; release state and audit event commit atomically.
- Concurrent duplicate reviews result in exactly one successful state transition and one transition audit event.
- Focused and full offline tests pass, and an isolated PostgreSQL integration test exercises multi-instance behavior.
- Roadmap distinguishes implemented shared storage from target deployment operations still requiring external environment validation.
