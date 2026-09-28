# Data-source credential protection and approval gate

## Background and goal

`connect_config.db_pwd` and private fields in connector parameters are currently persisted in ordinary database columns. The Serve data-source service has no approval lifecycle, and connector creation does not reject an unapproved configuration. This P0 change adds encrypted-at-rest credentials, explicit approval state, and a server-side connection gate without replacing DB-GPT's Python data-source stack.

## Scope

- Include DB-GPT Serve `connect_config` persistence, sensitive connector parameters, connector creation/use, approval endpoints, append-only approval audit, schema/upgrade SQL, and an explicit legacy credential migration command.
- Include authenticated approval through the DB-GPT App identity dependency; only a verified `admin` can approve, and a requester cannot approve their own change.
- Exclude production Secret Manager integration, rotation automation, enterprise IdP provisioning, database read-only grants/RLS, and changes to `.env` or secrets.

## User behavior

### AC-01: Credentials are encrypted at rest

- New and updated private connection fields are encrypted before database writes using a configured Fernet key supplied by the runtime environment.
- Missing/invalid key fails closed for a password-bearing create/update and for connecting to an encrypted datasource. File-based datasources without secrets remain usable subject to approval.
- Responses and logs never contain plaintext or ciphertext secrets. Connector construction decrypts only in process memory immediately before building the connector.
- Verification covers password fields and privacy-tagged extension parameters, database persistence, connector use, and API/log redaction.

### AC-02: Datasource changes require independent approval

- New rows start in `pending` state. Any connection-affecting update resets the row to `pending` and evicts the connector cache.
- Only a verified App identity with `role == admin` can approve or reject. The actor ID comes from `UserRequest`, never from request fields. The submitter cannot approve their own change.
- Each decision records actor, timestamp, decision, and a reason in an append-only audit row in the same database transaction as the status change.
- `ConnectorManager` rejects pending/rejected configurations at the shared connector resolution boundary so Agent, summaries, refresh, and direct service paths cannot bypass the gate.

### AC-03: Existing plaintext records are migrated explicitly

- Existing records are not silently treated as approved. A dry-run-first bounded CLI encrypts legacy secrets and marks each migrated datasource `pending` so an administrator can re-review it.
- Applying the migration requires an explicit `--apply` flag and a configured encryption key. Failed rows remain unchanged and are reported by datasource ID only.
- The migration is idempotent, does not print credentials, and supports rerun after partial failure.

## Security and compatibility

- Use existing `FernetEncryption` support where its API fits; do not add a new cryptography dependency.
- Expand the stored password column to a text-capable type so Fernet ciphertext is not truncated. Add approval metadata and the audit table with additive, reversible schema/upgrade steps for supported metadata databases.
- Legacy plaintext rows remain blocked until migrated and approved. This is an intentional fail-closed upgrade behavior.
- Serve routes protected only by API keys cannot claim a human approval identity. Approval actions must be exposed through an App route that resolves `UserRequest`; Serve-side service methods still enforce state transitions and actor arguments.
- Do not modify existing `.env`, keys, tokens, CI/CD, or production data.

## Assumptions and approval

- [x] The user authorized database operations, including schema changes and migrations.
- [x] The implementation follows the fail-closed legacy policy: migrated historical sources become `pending` and must be re-approved before use.
- [x] Approval is admin-only through verified `UserRequest.role` and `user_id`; API-key-only approval is not accepted.

## T003: Transfer an existing datasource owner

- Only a verified OIDC admin can transfer a datasource to an explicit owner ID.
- The owner transfer updates `submitted_by` and `user_id`, clears prior approval metadata, and sets the datasource to `pending` in one transaction.
- The existing append-only approval audit table records the admin actor and a JSON reason containing old owner, new owner, and operator reason; no schema change is required.
- The App route invalidates the datasource connector cache after a successful transfer. The destination owner must receive a fresh approval before the connector can be used.
- Request data cannot supply the actor ID. Empty/oversized owner IDs are rejected, same-owner transfers are rejected, and unknown datasource IDs fail without audit side effects.
- Verification: isolated SQLite DAO transaction and App route tests; no production metadata database is modified.

## Approval

- Spec status: approved for implementation.
- Approval source: user explicitly authorized all database operations on 2026-09-25; implementation follows this documented fail-closed plan and does not touch production data or secrets.
