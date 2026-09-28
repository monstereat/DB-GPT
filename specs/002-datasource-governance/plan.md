# Implementation plan: data-source credentials and approval

## Confirmed context

- `connect_config.db_pwd` is currently `String(255)` and DAO reads/writes plaintext.
- Connector Manager resolves stored passwords directly before constructing connectors and caches connectors by datasource name.
- Serve endpoints use an API key dependency and do not provide a human approver identity.
- DB-GPT App's `get_user_from_headers` supplies a verified `UserRequest` with user ID and role; existing data-source owner checks use this identity.
- The Serve flow package already uses `FernetEncryption`; reuse its implementation/configuration pattern where practical.

## Proposed decisions

1. Legacy sources become `pending` after explicit migration and require independent admin approval. No automatic approval based on historical activity.
2. Approval requires authenticated `UserRequest.role == "admin"` and a nonempty verified `user_id`; approval endpoints live in the App API, and the service transition validates actor and submitter.
3. Missing encryption key fails closed for secret-bearing writes and connector access. Key material is injected by the operator; this task adds configuration/docs but does not edit `.env` or put keys in the repository.
4. The migration defaults to dry-run, requires `--apply` to write, processes bounded batches, and reports datasource IDs/status only.

## Approach

1. Add explicit encryption/decryption helpers for privacy-tagged datasource fields, preserving non-secret fields and API response redaction. Ensure writes encrypt exactly once and connector creation decrypts only after approval passes.
2. Add status, submitter, and approval metadata to `connect_config`; add append-only approval audit rows. Update SQLAlchemy model registration and supported SQLite/MySQL schema initialization/upgrade scripts.
3. Implement transactional service methods for submit/review, forbid self-approval, reject invalid transitions, and expose review operations through verified App API routes. Keep approval actor out of request body.
4. Enforce `approved` at the shared ConnectorManager boundary before cache lookup/creation; pending/rejected state must also evict stale cached connectors on update/rejection.
5. Add the dry-run/apply legacy migration command; test plaintext-to-ciphertext conversion, approval reset, partial rerun, and secret-free output on temporary databases.
6. Run focused Serve/App tests, supported schema migration tests, relevant package regressions, Ruff/format/compile checks, and diff/scope checks; update roadmap with precise limits.

## Expected files

| Area | Expected changes |
| --- | --- |
| Serve data-source DAO/service/API | encrypted persistence, approval state/audit, strict transitions, response safety |
| Connector Manager and App API | connector gate/cache invalidation, verified admin approval route |
| Metadata schemas and upgrades | additive SQLite/MySQL column/table migration and password width expansion |
| CLI/tests/docs | bounded migration command, regression coverage, operator key/approval instructions |
| `docs/develop-me-roadmap.md` | completion evidence and remaining production limits |

## Verification

- Unit tests: no plaintext or ciphertext in responses/logs; encrypted values round-trip; no key fails closed; non-admin/self-approval rejected; pending/rejected connector access blocked; approved access allowed.
- Migration tests: dry-run does not mutate; apply encrypts and marks pending; interrupted/repeated apply is idempotent; audit records are atomic.
- Schema tests: fresh schema and upgrade path both expose required metadata and preserve datasource rows.
- Integration tests: temporary SQLite and MySQL metadata stores; connector mock confirms authorization precedes cache use/creation.
- Quality: Ruff check/format, `py_compile`, package regression suites, `git diff --check`, and controlled scope gates.

## Risks

- Legacy datasource access pauses until key injection, migration, and admin reapproval. This is the chosen fail-closed default.
- Adding approval to every path that can open a Serve datasource is required; a UI/API-only gate is insufficient.
- Fernet key loss makes encrypted credentials unrecoverable. Key backup/rotation and Secret Manager operation remain outside this implementation.
- Existing concurrent processes may hold live connector objects; deployment must restart or explicitly invalidate all connector caches after migration/approval changes.

## Approval

- Plan status: approved for implementation.
- Approval source: user explicitly authorized all database operations on 2026-09-25; scope remains limited to local code/schema migration support and temporary test databases.
