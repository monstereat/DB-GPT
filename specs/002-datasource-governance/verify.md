# Verification: data-source credentials and approval

## Verification evidence

- Serve datasource regression: 14 passed, including encrypted persistence round-trip, missing-key rejection, cache-before-approval denial, independent approval, atomic audit, and dry-run/apply/reapply migration behavior on a temporary SQLite metadata database.
- App API v1 regression: 87 passed, including redaction, verified-admin review, owner authorization, and existing API behavior.
- Temporary MySQL 8.4 smoke created a legacy `connect_config`, applied the datasource upgrade DDL, ran migration dry-run and batch-size-one apply, then confirmed pending state, retained submitter, encrypted prefix, and audit table. The temporary container was removed.
- Ruff check/format, Python compile, and `git diff --check` passed. The connector manager contains a pre-existing unused local `sid`; Ruff was run on that file with only F841 ignored so unrelated code was not changed.

## Owner-transfer verification

- Serve DAO and App datasource API focused suite: 26 passed.
- DAO regression verifies old/new owner audit data, atomic approval reset to `pending`, rejection of a same-owner no-op, and no duplicate audit event.
- App API regression verifies a verified OIDC admin can transfer ownership and that the connector cache is invalidated; an unverified development admin is rejected.
- Ruff check, Ruff format check, `compileall`, and `git diff --check` passed. No schema migration or production metadata database access was performed.

## Deployment limits

- The user's metadata databases were not migrated. Set a durable key through a secret manager, run dry-run, schedule the apply migration, then have an independent verified OIDC admin review every legacy datasource.
- Cache invalidation prevents subsequent connector lookups after reject/update, but cannot terminate work already holding a connector reference. It also does not configure production Secret Manager lifecycle, read-only database grants, tenant/region RLS, or enterprise IdP policy.
- MySQL upgrade SQL is versioned under `assets/schema/upgrade/v0_8_2/`; the migration CLI expects that DDL to be applied first. SQLite schema expansion is performed by the CLI only when `--apply` is supplied.
