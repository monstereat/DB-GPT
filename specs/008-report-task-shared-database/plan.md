# Plan: shared report task database

1. Adapt the report task store to SQLAlchemy Core while preserving SQLite path shorthand and encryption behavior.
2. Implement PostgreSQL-safe atomic claims with `FOR UPDATE SKIP LOCKED` and keep SQLite's `BEGIN IMMEDIATE` path.
3. Allow configuration of a SQLAlchemy URL and document the PostgreSQL deployment form and driver requirement.
4. Add backend coverage for SQLite compatibility and shared-database configuration; run task/API regressions and static checks.
5. Update the roadmap and verification evidence, leaving live production acceptance open unless a PostgreSQL service is available.
