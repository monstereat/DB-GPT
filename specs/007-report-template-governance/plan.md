# Plan: report template governance

1. Add a SQLite template release store with validation, seed data, two-person review, deterministic snapshots, and append-only audit.
2. Add admin API routes for release listing/audit/submission/review; expose published versions through the runtime catalog.
3. Integrate the runtime catalog into sync export and task snapshot creation while retaining existing download-time hash validation.
4. Add store, API, and snapshot-pinning tests; run the full enterprise Text-to-SQL suite and lint/format checks.
5. Update the roadmap and verification record, explicitly retaining production storage and deployment requirements as open.
