# Tasks: shared report task database

## T001: Support SQLAlchemy database URLs

- Acceptance criteria: local paths keep working as SQLite; SQLAlchemy URLs initialize the task store without changing task semantics.
- Status: complete

## T002: Make claims safe across database instances

- Acceptance criteria: PostgreSQL uses transactional row locking with `SKIP LOCKED`; SQLite retains serialized atomic claims.
- Status: complete

## T003: Verify and update operational docs

- Acceptance criteria: targeted regressions and static checks pass; README and roadmap clearly state supported configuration and outstanding deployment evidence.
- Status: complete
