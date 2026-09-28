# Shared database storage for report tasks

## Goal

Allow the enterprise Text-to-SQL report task queue to use a shared SQLAlchemy database URL, so API and worker processes can share durable task state across instances while retaining the current SQLite demo behavior.

## Scope

- Keep filesystem paths as SQLite shorthand and accept SQLAlchemy database URLs.
- Preserve task idempotency, actor-scoped reads, encrypted results, retention, and lease behavior.
- Use row-level locking with `SKIP LOCKED` when claiming work on PostgreSQL; preserve SQLite's immediate transaction claim behavior.
- Document database driver/configuration requirements and that database backup, TLS, grants, and secret delivery remain operator responsibilities.
- Do not migrate the main DB-GPT metadata schema or change the demo business database.

## Acceptance criteria

- Existing SQLite report-task API and store behavior remains compatible.
- A PostgreSQL URL can initialize the same task schema and support enqueue, claim, completion, and actor-scoped reads.
- Concurrent workers do not claim the same task when using PostgreSQL row locks.
- Targeted report task and API regressions pass; roadmap and verification record distinguish implemented storage support from unverified deployment operations.
