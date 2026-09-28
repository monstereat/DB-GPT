# Enterprise Text-to-SQL: guarded SQLite MVP

Standalone reference implementation for the DB-GPT enterprise analytics project. The fixture contains synthetic users, regions, products, orders, order items, and refunds. `api.py` demonstrates OIDC identity-to-tenant authorization for SQL and versioned metric endpoints; it is not wired into DB-GPT's default Agent SQL execution pipeline.

See [business_dictionary.md](business_dictionary.md) for the overview, [schema_metadata.json](schema_metadata.json) for machine-readable table/column descriptions, sensitivity, tenant keys, relations, and the local read-only source profile, and [metric_catalog.json](metric_catalog.json) for versioned metric formulas. `semantic_metrics.py` recursively compiles registered metrics through their pinned dependency versions into SQL and only accepts registered dimensions; tenant-scoped query allowlists are generated from the Schema metadata.

## Why this example exists

A generated SQL string should never be executed directly with production database credentials. This demonstration enforces three independent restrictions:

1. SQLite URI opens the selected database in read-only mode.
2. SQLite's native authorizer accepts only SELECT, approved functions, and reads from explicitly allowed tables and columns.
3. In tenant mode, connection-local views filter every table by a server-owned tenant ID and project away sensitive fields.
4. A time budget and server-enforced maximum row count limit each query.

The example returns columns and rows as JSON-compatible Python objects.

`gold_questions.json` contains 50 Chinese business questions with fixed expected results, including net sales, category-level weighted unit prices, unsold products, regional completion and refunded-order rates, order-level refunds, quarter boundary cases, customer sales share, the South China quarterly sales/refund-rate acceptance scenario, and three follow-up cases with their prior-turn context. Each question has one primary benchmark category and explicitly declares whether row order is semantically significant. Unordered answers compare as a multiset of complete rows (so duplicates still matter); monthly series and Top 3 ranking questions require the expected order. Both fixed-SQL and live-Agent scorecards use this rule. The fixed SQL scorecard reports accuracy and missing/rejected/incorrect counts per category plus the unweighted macro-average, so regressions in smaller categories remain visible. `gold_candidates.json` supplies the fixed SQL for exercising the evaluator; passing it proves fixture and result-comparison consistency, not live model accuracy.

## Run

```bash
cd examples/enterprise-text2sql
python -m pip install -r requirements-test.txt
PYTHONPATH=../../packages/dbgpt-core/src:../../packages/dbgpt-serve/src:../../packages/dbgpt-ext/src \
  python -m pytest -q
```

The same requirements file supports the Serve quota storage and ReAct metering
regression suite from the repository root:

```bash
python -m pip install -r examples/enterprise-text2sql/requirements-test.txt
PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:packages/dbgpt-ext/src:packages/dbgpt-app/src \
  python -m pytest -q -o addopts='' \
  packages/dbgpt-serve/src/dbgpt_serve/token_quota/tests/test_dao.py \
  packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_token_quota.py
```

The standalone Vue 3 + ECharts dashboard is in [`ui/`](ui/README.md). Start
the API below, then run `npm install && npm run dev` from `ui/`; the Vite dev
server proxies `/api` requests to the local API. Set `DBGPT_AGENT_ORIGIN` if
DB-GPT is not listening at its default local address. The page accepts a
short-lived OIDC access token in memory, previews metric SQL, displays
tenant- and region-scoped summary metrics, and can stream a separate DB-GPT
ReAct answer for a user-authorized datasource. The ReAct datasource must have
database-enforced tenant/region policies; it does not use the demo API's
SQLite tenant executor. Successful `sql_query` steps stream up to 50 structured
rows, capped at 128 KiB, alongside the Agent's existing table output; the page
displays those rows and charts numeric columns from that same result. This Agent chart follows the
selected DB-GPT datasource's authorization and database policies, not the
separate demo metric endpoint's tenant executor.

The DB-GPT ReAct metric fast path uses the datasource's configured published
catalog and aliases. This synthetic catalog declares `default_year: 2026`, so a
question with an explicit quarter or month but no year uses 2026. Questions that
mention multiple metrics, unsupported groupings, comparisons, or sorting do not
use this single-metric fast path; general Agent handling for those questions is
not covered by the targeted smoke checks below.

The HTTP API only opens an existing demo database. It exposes `POST /query` for guarded read-only SQL, `POST /metrics/query` for registered metrics, `POST /reports/export` for authenticated XLSX, and `POST /reports/export.pdf` for authenticated server-generated PDF. `POST /reports/tasks` queues an XLSX report; send a printable `Idempotency-Key` header, then poll `GET /reports/tasks/{task_id}` and download a completed file from `GET /reports/tasks/{task_id}/export.xlsx`. Tasks persist separately from the demo data. By default they use `<demo database>.report-tasks.sqlite3`; set `DBGPT_REPORT_TASK_DB` to choose a local SQLite path. For shared API/worker instances, set `DBGPT_REPORT_TASK_DATABASE_URL` to a PostgreSQL SQLAlchemy URL such as `postgresql+psycopg://user:password@db-host:5432/dbgpt_tasks`; install the matching PostgreSQL driver in each process and keep credentials in the deployment secret manager. SQLite task files are created with mode `0600`. A Fernet key is required before single or batch report tasks can be enqueued; without one, enqueue APIs return `503` and no task is persisted. Generate a local demo key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`, then configure it as `DBGPT_REPORT_ENCRYPTION_KEY`. For deployments, inject the key from the secret manager. Alternatively, set `DBGPT_REPORT_ENCRYPTION_KEYS` to a comma-separated key ring ordered active-first. New rows use the first key; reads try all configured keys, so deployments can put a new key first while retaining old keys for existing rows. This requires the `cryptography` package (included in `PyJWT[crypto]`). Reads fail closed if an encrypted result is opened without a matching key; legacy plaintext results are never served and need an explicit migration. The key ring supports staged key changes for new writes and reads with retained old keys. To encrypt legacy plaintext results or rotate old ciphertext, put the active key first in `DBGPT_REPORT_ENCRYPTION_KEYS` and run `python examples/enterprise-text2sql/migrate_report_results.py --database <report-task-db>`; the command updates successful report rows in bounded transactions, and old keys should remain configured until migration completes. A retention utility is available with an explicit UTC cutoff; it counts by default and only deletes succeeded/failed tasks when `--apply` is supplied: `python examples/enterprise-text2sql/prune_report_tasks.py --database <report-task-db> --before 2026-01-01T00:00:00Z`, then add `--apply` after reviewing the count. No retention duration or schedule is configured by the demo. PostgreSQL task storage uses transactional row locks and `SKIP LOCKED` claims, while a unique actor/idempotency constraint makes concurrent duplicate submissions converge on one task. The store initializes its own `report_tasks` table and indexes. A live PostgreSQL concurrency/deployment acceptance run, TLS, least-privilege grants, backups, secret-manager setup, and retention/key operations are still required before production use. The worker uses atomic claims, 30-second renewable leases, lease-expiry recovery, and up to two attempts. Idempotency is scoped to the authenticated actor and includes the requested report and enqueue-time identity/policy snapshot; the snapshot contains no bearer token. Reusing a key with a changed request or scope returns `409`. Task status/download require the current actor; downloads also require the current tenant, region, role, data source and policy version to match the saved authorization snapshot. The job pins the approved metric catalog version and its content hashes at enqueue time, and uses that same snapshot after retries or restarts. Both synchronous report formats use the same server-owned tenant/region executor, metric definitions, versions, date range and audit event; request bodies cannot supply identity scope. PDF uses ReportLab's built-in Simplified Chinese CID font by default. Set `DBGPT_PDF_FONT` to a server-available CJK TrueType font to embed it for consistent rendering across PDF viewers; minimal Poppler installations without Adobe-GB1 CMap data may not render the default CID font. Reports include generation time, authorized tenant/region scope, date range, metric versions/definitions and filtered values. Metric requests may provide `metric_version`; otherwise the catalog's default published version is selected. `paid_refund_amount` versions `1.0.0` and `2.0.0` attribute refunds to refund date and original order date respectively. `net_sales_amount` and `refund_rate` versions `1.0.0` and `2.0.0` pin those corresponding refund definitions, so the cohort versions group refunds by original order date. Derived metrics pin the exact versions of their dependencies. Metric dimensions support tenant-scoped region aggregates and monthly trends; monthly queries group by the metric's registered period field. Registered metric results use a 30-second TTL and a cache key derived from authenticated scope, metric definition, and SQLite database/WAL/journal file version. By default, a bounded process-local LRU is used. Set `DBGPT_METRIC_CACHE_REDIS_URL` and install `redis-py` to share the TTL cache across API workers; the Redis key hashes the full scope, while each request still rechecks authorization. Redis read/write failures bypass caching and run the guarded database query. File-version changes produce new keys and old entries expire by TTL. Configure Redis memory limits and an eviction policy in the Redis deployment; production should use TLS (`rediss://`) and an ACL-scoped account. Query audit logs contain the authenticated user/tenant, source and policy versions, SQL hash, status, duration and row count; they exclude raw SQL. Create the synthetic fixture first, then start the API from the repository root:

`POST /reports/batches/tasks` queues one XLSX for 2–10 named scenarios. Each scenario has its own metric set, date range, and optional dimension. The entire batch succeeds or fails as one task: if any scenario fails, no partial workbook is stored or downloadable. Reuse the task status and download endpoints above; the workbook tags every metric definition and result row with its scenario name. Batch requests use the same actor, tenant/region, role, metric allowlist, pinned catalog snapshot, idempotency, encryption, and download-time authorization checks as single-report tasks.

`gross_margin_rate@1.0.0` uses completed order detail revenue (`quantity × unit_price_cents`) and product cost (`quantity × internal_cost_cents`), grouped by order date; refunds do not reduce this metric. Only authenticated `admin` users can query it. The cost column remains unavailable through `/query`; only the server-compiled metric path can read it, and that path remains tenant/region scoped. A zero revenue denominator returns `null`. The metric can be exported only with the admin-only `admin-margin@1.0.0` template; the sales templates cannot include it.

Synchronous XLSX/PDF exports and asynchronous single/batch XLSX tasks use the server-owned, versioned template catalog seeded from `report_templates.json`. Clients may select only a registered `template_id`; free-form `fields` remain rejected. The `sales-standard@1.0.0` and `sales-compact@1.0.0` templates allow `admin`, `normal`, and `sales` to export the four registered sales/refund metrics and define their own definition/result columns. The `admin-margin@1.0.0` template is admin-only and additionally allows `gross_margin_rate`. That metric's compiler-approved query is executed only through the admin tenant/region-scoped cost executor; raw `/query` still cannot access `internal_cost_cents`. Batch scenarios must share a template. Async tasks persist the template snapshot and SHA-256 alongside the metric snapshot, then verify and use that snapshot during processing and download, so catalog edits do not change queued report columns or metric access. By default the template catalog is seeded from `report_templates.json` into the demo SQLite database. Admin APIs at `GET /reports/templates/releases`, `GET /reports/templates/releases/audit`, `POST /reports/templates/releases`, and `POST /reports/templates/releases/{template_id}/review` provide versioned submissions, independent approval/rejection, and append-only audit. `GET /reports/templates/available` returns published templates allowed for the caller role. Only a different admin can approve a draft. New definitions are checked against the registered roles, metrics, export policy, and output fields before they enter the catalog. Existing task snapshots remain pinned. To share releases and approvals across API instances, set the explicit `DBGPT_REPORT_TEMPLATE_DATABASE_URL`, for example `postgresql+psycopg://<user>:<password>@<host>:5432/<database>`, and install the matching SQLAlchemy driver (such as `psycopg`) in every API process. Keep credentials in the deployment secret manager; do not commit them. This setting is independent of `DBGPT_REPORT_TASK_DATABASE_URL`. The template store initializes its own tables and audit immutability triggers. Target deployment permissions, TLS, backups, key, and retention management remain deployment responsibilities.

Metric releases use the demo SQLite database's additive `metric_releases` and append-only `metric_release_audit` tables. `POST /metrics/releases` submits a validated immutable metric version as a draft; an identified `admin` other than the submitter must call `POST /metrics/releases/{metric_id}/{version}/review` with an approval decision and reason. Approval atomically changes the published default and adds the audit event. `GET /metrics/catalog`, `/metrics/releases`, and `/metrics/releases/audit` are admin-only. Runtime metric queries and reports compile from the persisted published catalog, whose snapshot includes default versions, catalog version, and per-version content SHA-256 hashes. This SQLite workflow is for the isolated demo and does not migrate DB-GPT's application database.

```bash
uv run --no-project --with sqlglot python examples/enterprise-text2sql/ecommerce_demo.py \
  --database /tmp/dbgpt-ecommerce-demo.sqlite

ENTERPRISE_TEXT2SQL_DB=/tmp/dbgpt-ecommerce-demo.sqlite \
PYTHONPATH=packages/dbgpt-core/src:packages/dbgpt-serve/src:examples/enterprise-text2sql \
  uv run --no-project --with fastapi --with uvicorn --with 'PyJWT[crypto]' \
  --with sqlglot --with openpyxl --with reportlab --with 'SQLAlchemy>=2.0.25,<3' \
uvicorn api:app --app-dir examples/enterprise-text2sql --host 127.0.0.1 --port 8000
```

For a shared cache, install `redis-py` in the API environment and set
`DBGPT_METRIC_CACHE_REDIS_URL` there (for example,
`redis://127.0.0.1:6379/0` for local development). Do not commit credentials.

Configure `DBGPT_OIDC_ISSUER`, `DBGPT_OIDC_AUDIENCE`, and claim mappings as described in [`docs/develop-me-roadmap.md`](../../docs/develop-me-roadmap.md). Map the authenticated tenant claim to `tenant_id` (`tenant-a` or `tenant-b` in this fixture). Map sales roles to `sales` and include their server-issued `region_id` claim (`a-gz`, `a-sz`, or `b-gz`); region views constrain orders, refunds, order items, and products. The request body accepts only SQL; client-supplied tenant or region values are rejected. Missing tenant or a missing sales region fails closed.

To inject the business dictionary into DB-GPT ReAct prompts, configure the DB-GPT app process with a server-owned datasource-to-file mapping. The mapping key must exactly match the authorized DB-GPT datasource name; the file path and text are never accepted from the browser request. For example:

```bash
DBGPT_DATABASE_CONTEXT_FILES='{"ecommerce-demo":"/absolute/path/to/examples/enterprise-text2sql/business_dictionary.md"}'
```

The app loads UTF-8 files up to 32 KiB into the main and dispatched sub-agent prompts. This provides business definitions as context only; SQL execution still depends on database read-only credentials and database-side tenant/region policies.

To apply the machine-readable sensitive-column metadata to ReAct raw SQL, configure a separate datasource-to-schema mapping in the DB-GPT app process:

```bash
DBGPT_DATABASE_SCHEMA_FILES='{"ecommerce-demo":"/absolute/path/to/examples/enterprise-text2sql/schema_metadata.json"}'
```

The read-only SQL tools used by the main and dispatched ReAct Agents reject references to columns classified as personal or confidential, reject wildcards on tables that contain protected fields, and prevent selecting/grouping/ordering by tenant keys marked non-queryable. Tenant keys remain usable in joins and filters. The same server-owned schema mapping must declare `source.tenant_column` and include that key on every registered physical table; both Agent SQL tools inject a tenant predicate for each physical table and fail closed when a trusted tenant scope or mapped table policy is missing. For role `sales`, `source.region_scope` must also define a direct region column or a registered relationship through orders/order items for each queried table. Other roles remain tenant-scoped. The exact datasource mapping and schema file are operator-controlled; invalid or incomplete policy fails closed.

This is application-level filtering for the ReAct `sql_query` path. It supplements, and does not replace, read-only database credentials and database grants/RLS. Every referenced physical table must appear in the server-owned schema mapping; unregistered tables fail closed. Registered views are expanded only when the operator provides a single-SELECT, one-table, direct-column projection definition whose exposed columns exactly match the metadata and are public business fields. The expanded base-table query receives the same tenant/region filters and column checks. Joins, expressions, nested/unknown views, missing definitions, and sensitive projections remain rejected. Other execution paths still require their own authorization coverage.

To let the main and dispatched ReAct Agents look up published metric versions on demand, configure a server-owned datasource-to-catalog mapping in the DB-GPT app process:

```bash
DBGPT_METRIC_CATALOG_FILES='{"ecommerce-demo":"/absolute/path/to/examples/enterprise-text2sql/metric_catalog.json"}'
```

The read-only `metric_catalog` tool returns registered metric definitions, units, default versions, and pinned dependency versions for the already-authorized datasource. A catalog entry may set `allowed_roles` to a nonempty list of DB-GPT internal roles (for example `"allowed_roles": ["admin"]`); both listing and execution use the role from the verified server-side identity, and a role-restricted default version is hidden from other roles. The loader rejects a public derived metric that depends on a restricted metric. This restricts semantic metric access only; it does not grant database permissions or protect raw SQL from the database, so confidential fields still require database-side controls. The `metric_query` tool accepts a published metric, date range, optional region/month dimension, and optional version; it compiles pinned dependencies deterministically and sends the resulting SQL through the same `sql_query` read-only validation, timeout, row limit, and audit path. The compiler supports SQLite, PostgreSQL, and MySQL month expressions. Neither tool accepts a request-supplied catalog path, table name, column name, or SQL. Files larger than 128 KiB or catalogs with invalid structure are ignored.

### Keycloak OIDC provider setup

This example uses a Keycloak Realm as its reference identity provider. Create a confidential or public OIDC client for the API/UI, configure the access token audience to match `DBGPT_OIDC_AUDIENCE`, and ensure its access token includes the claims below. Use protocol mappers or client scopes to issue `organization.tenant` and `region_id`; assign realm roles named `analytics-user`, `analytics-admin`, or `regional-sales` as appropriate.

For a Vue browser login, use a public client with Standard Flow enabled, client authentication disabled, and PKCE S256 required. Register the exact UI callback URL (for example, `http://localhost:5173/`) as a valid redirect URI and the UI origin as a Web Origin. Add an Audience mapper to the UI client's dedicated scope for the API audience configured below, and enable **Add to access token**. The API validates the access token's `aud`; an audience present only in the ID Token is insufficient. Keycloak's Audience mapper can add a client ID or custom audience to the access token [as documented by Keycloak](https://www.keycloak.org/admin-api/protocol-mappers).

Add the tenant and region as user attributes (for example, `tenant=tenant-a` and `region_id=a-gz`). In the OIDC client scope, add User Attribute mappers with **Add to access token** enabled: map `tenant` to claim name `organization.tenant` with JSON type `String`, and map `region_id` to claim name `region_id` with JSON type `String`. Keycloak treats dotted claim names as nested JSON, so the first mapper produces `{"organization":{"tenant":"tenant-a"}}`. Keep the realm roles mapper in the access token so `realm_access.roles` is an array. The server maps these token paths; it never accepts tenant or region values from the browser request.

On Keycloak 26, also define `tenant` and `region_id` in **Realm settings → User profile** as custom attributes before assigning them to users. The default profile only permits the built-in fields; undeclared custom attributes may be discarded and then omitted from access tokens. Restrict who can view/edit these authorization attributes to administrators, and manage them through trusted provisioning.

| DB-GPT identity field | Example Keycloak access-token claim | Purpose |
| --- | --- | --- |
| `user_id` | `sub` (built-in default) | Stable authenticated subject |
| `user_name` | `preferred_username` (built-in default) | Display/login name |
| `tenant_id` | `organization.tenant` | Server-side tenant row scope |
| `region_id` | `region_id` | Required row scope for `sales` |
| `role` | `realm_access.roles` | External role names, then mapped below |

Set these values in the DB-GPT Serve process environment. Replace the example issuer, audience, and role names with the exact values configured in your Realm/client; do not put production credentials or tokens in the repository.

```bash
DBGPT_OIDC_ISSUER=https://id.example.com/realms/analytics
DBGPT_OIDC_AUDIENCE=dbgpt-api
DBGPT_OIDC_CLAIM_MAPPINGS='{"tenant_id":"organization.tenant","region_id":"region_id","role":"realm_access.roles"}'
DBGPT_OIDC_ROLE_MAPPING='{"analytics-user":"normal","analytics-admin":"admin","regional-sales":"sales"}'
```

At startup/request time the API reads the issuer's `/.well-known/openid-configuration`, obtains its JWKS URI, and verifies the Bearer JWT signature and issuer/audience/time claims before applying these mappings. Role arrays are accepted only when their mapped internal roles converge to one value; missing or conflicting roles become `normal`. The `sales` endpoint policy separately rejects identities without a tenant or region. Production must use HTTPS and a trusted issuer. `DBGPT_OIDC_ALLOW_INSECURE_HTTP=true` is only for loopback OIDC tests and local IdP development. Automated tests exercise Discovery, JWKS retrieval, RSA validation, claim mapping, and authorization. A local Keycloak 26 Realm smoke also used a real signed access token against the running API: `analytics-user` was scoped to `tenant-a`, `regional-sales` with `region_id=a-gz` saw only four matching orders, and a client-supplied tenant override was rejected with 422. The smoke used an isolated test Realm and disposable synthetic credentials; it did not exercise the browser PKCE flow. A real enterprise Realm, its HTTPS/CORS/redirect URI settings, and production data authorization still need environment-specific validation.

### Datasource credential encryption and approval

Set `DBGPT_DATASOURCE_ENCRYPTION_KEY` to a stable, high-entropy key supplied by the deployment secret manager. The service fails closed for secret-bearing datasource writes and connector use when the key is missing, and it never falls back to an ephemeral key. New or edited sources enter `pending`; connector resolution checks approval before using its cache. Only a verified OIDC `admin` can approve or reject, and the submitting user cannot approve their own source. Approval decisions are recorded in `datasource_approval_audit`. Serve API-key routes do not expose approval actions.

For an existing SQLite metadata database, run the migration first in dry-run mode, then apply it during a maintenance window. It adds the SQLite lifecycle columns, encrypts legacy password and privacy-tagged connector fields, and sets sources to `pending`. For MySQL, first apply `assets/schema/upgrade/v0_8_2/upgrade_to_v0.8.2.sql`; then run the same data migration. The command requires `DBGPT_METADATA_DATABASE_URL`, and `--apply` additionally requires `DBGPT_DATASOURCE_ENCRYPTION_KEY`:

```bash
python tools/migrate_datasource_credentials.py
python tools/migrate_datasource_credentials.py --apply --batch-size 100
```

The migration prints datasource IDs and error classes only. After migration, an independent administrator reviews sources through `GET /api/v1/chat/db/approvals/pending`, then submits `POST /api/v1/chat/db/{db_name}/approval` with `{"decision":"approve"}` or `{"decision":"reject","reason":"..."}`. Legacy sources remain unavailable until approved. Cache invalidation blocks subsequent connector lookups after a decision; already-running callers holding a connector reference may continue until their operation ends or the process restarts. This does not configure production database grants, read-only accounts, tenant/region RLS, or key rotation.

### Optional daily Agent token quota

Set `DBGPT_DAILY_TOKEN_LIMIT` to a positive integer to enable a shared per-tenant, per-user UTC-day token budget for plain-text `ChatNormal`, ReAct, and knowledge-agent model calls. For compatibility, `DBGPT_REACT_DAILY_TOKEN_LIMIT` remains a ReAct/knowledge-agent fallback when the shared setting is unset; the shared setting takes precedence. The budget is reservation-based, not a provider-enforced hard spend ceiling: before each call, the service serializes text messages (including prior tool-call arguments and tool results), tool schemas and `tool_choice`, counts them with the worker tokenizer, then reserves that estimate plus `max_new_tokens` and a framing allowance. Non-string/multimodal message content is rejected while the budget is enabled because this generic path cannot reliably estimate provider image/audio token use. Provider message conversion and tokenizer differences can still make a single text call exceed the configured budget; that overage is recorded and blocks later calls, but cannot undo provider usage already incurred. Missing usage and interrupted calls are charged at the reserved estimate. Active streams refresh reservation leases; a later request for the same user recovers stale pending reservations by charging their full reserved amount. This requires verified OIDC identities with both `sub` and a mapped `tenant_id`; when enabled, development identities or missing tenant claims are rejected. The usage tables are part of the DB-GPT Serve schema: SQLite creates them through model initialization, while MySQL deployments must apply the matching schema/upgrade SQL before enabling this setting. Leave both variables unset to disable budgets. Prompt-template debug and knowledge document summary use the shared MeteredLLMClient with verified per-user quota context. Serve evaluation, LLM benchmark execution, and the volatility sub-agent fail closed when either quota setting is enabled because they lack trusted per-user quota context. ReAct and knowledge-agent Tree/Hybrid retrieval use the same verified per-user MeteredLLMClient for tree keyword extraction. Direct Serve retrieval and recall-test APIs fail closed for Tree/Hybrid or KnowledgeGraph spaces because they have no per-request metered identity path. KnowledgeGraph document indexing is blocked before task dispatch; pure VectorStore retrieval and embedding indexing remain available. AWEL flow endpoints fail closed when the shared daily quota is enabled. These guarded paths are not metered and are unavailable while their guard is active. Custom AWEL/plugin model calls and provider billing hard caps remain outside quota coverage.

Run the standalone evaluator with a new synthetic database and a candidate JSON file:

```bash
uv run --no-project python evaluate_candidates.py \
  --database /tmp/dbgpt-ecommerce-demo.sqlite \
  --candidates gold_candidates.json
```

To include the separate policy regression suite, add `--security-candidates security_candidates.json`. Nineteen fixed attack cases check that sensitive/cross-tenant reads and aggregates, CTE name/column bypasses, recursive CTEs, direct `main` table access, SQLite PRAGMA statements/table-valued table and function listings, catalog introspection, file-reading/writing and extension functions, multiple statements, writes and malformed SQL are denied, and that a foreign-region filter returns no rows. The scorecard reports results by sensitive-data, tenant-boundary, read-only/syntax, query-structure, schema-introspection and unsafe-function categories, plus an unweighted macro-average so a small category regression is visible. A separate executor test confirms the time budget interrupts an expensive read-only cross join over allowed rows.

To evaluate the DB-GPT App's Schema metadata column policy, add `--schema-security-candidates schema_security_candidates.json`. The evaluator calls the same SQLGlot check used by the ReAct `sql_query` tool against this example's `schema_metadata.json`, covering confidential columns through aliases/CTEs/subqueries, protected-table wildcards, tenant-key projections, safe aggregate/join controls, registered safe view expansion, unsafe view definitions, and unregistered view aliases/wildcards. The 15-case scorecard reports sensitive-column, wildcard, tenant-key, safe-query-shape, unregistered-object, and view-definition-audit categories with an unweighted macro-average; it contains only case IDs, decisions, and SQL hashes. Separate SQLite execution regression verifies tenant filtering after view expansion. This does not prove production database grants/RLS or coverage outside the ReAct tool.

To execute the ReAct tenant/region row-policy candidates, add `--row-scope-candidates row_scope_candidates.json`. This suite runs fixed SQL on the synthetic database after applying the same schema-mapped SQLGlot row filter as the main and dispatched ReAct SQL tools. It checks tenant-only access, direct region filters, refund/item/product relationship scopes, injected `OR 1=1` attempts, missing claims, unregistered tables, and schema-qualified sources. The scorecard reports tenant-isolation, region-scope, bypass-resistance, missing-identity, and unregistered-object categories with an unweighted macro-average. It exposes only case IDs, statuses, row counts, and SQL hashes; it does not validate database RLS or production identities.

To score semantic metric requests through the DB-GPT App implementation, add `--metric-candidates metric_candidates.json`. The evaluator invokes the published catalog loader and official `metric_query` compiler, then runs the compiled query through the same Schema column check, tenant/region row-scope injection, and read-only execution gateway. The 11 fixed cases cover sales, event-date and order-cohort refund definitions, pinned net-sales/refund-rate versions, region scope, admin-only gross margin, pre-execution denial for normal roles, and a zero-sales denominator. The scorecard reports base-metric, time-and-version-semantics, tenant/region-scope, restricted-metric, role-authorization, and zero-denominator categories with an unweighted macro-average. Expected values stay in the evaluator; reports include case ID, status, metric version, SQL hash, and row count without result values. This uses only the synthetic SQLite fixture and does not represent live Agent selection quality or production database authorization.

To add PostgreSQL/MySQL parser policy cases, pass `--dialect-security-candidates dialect_security_candidates.json`. The evaluator calls DB-GPT Core's shared `validate_read_only_sql` for each dialect and records only the decision, case ID, attack category, and SQL hash. It reports per-category pass rates and an unweighted macro average alongside the overall score, so a regression in a small class such as server file access remains visible. The fixed cases cover read-only control, writes/exports, server file access, resource exhaustion, session side effects, and multiple statements. This does not connect to either database or validate server grants, RLS, timeout cancellation, or driver behavior.

To score clarification decisions on six deliberately ambiguous questions, add `--ambiguity-candidates ambiguity_candidates.json`. Each candidate chooses `clarify` or `answer` and lists missing fields; the evaluator checks the action and exact missing-field set. These are fixed labels for validating the benchmark format and evaluator, not outputs from a live Agent and not a measure of model clarification quality. Scorecards contain status and hashes, not candidate text or question content.

To include fixed multi-turn authorization regressions, add `--multiturn-authorization-candidates multiturn_authorization_candidates.json`. Each scenario executes all turns against one server-owned tenant/region scope and checks whether a later tenant-switch, region-switch, or CTE follow-up is rejected or filtered while a subsequent in-scope query remains available. The scorecard exposes scenario IDs, turn statuses and SQL hashes only; this validates the guarded SQLite executor across turn sequences, not DB-GPT Agent decisions or production database RLS.

To score a running DB-GPT ReAct Agent against the 50-question gold set, set `DBGPT_AGENT_API_URL` to the trusted API origin, `DBGPT_AGENT_DATABASE` to a datasource visible to the authenticated user, and `DBGPT_EVAL_ACCESS_TOKEN` to a short-lived OIDC access token. Use a datasource containing the same tenant-scoped fixture rows as the gold answers; the server must enforce that scope. Then run:

```bash
cd examples/enterprise-text2sql
uv run --no-project python evaluate_agent.py
```

For a run-to-run stability check, pass `--runs 2` through `--runs 5`. The runner repeats the same gold questions with fresh conversation IDs and reports each run plus per-question correct rate, status counts, and distinct result-hash count. These aggregate fields contain no SQL or row values. Repeated runs are supported for the gold evaluation; the policy evaluator remains single-run.

The runner sends one question per new conversation to `/api/v1/chat/react-agent` and scores the structured `sql_result` event against expected columns and rows only when the SSE stream ends with the application `done` event. Its scorecard groups correct, incorrect, missing, invalid, truncated, incomplete-stream, and timed-out results by the gold question's primary category, reports an unweighted category macro-average, and records each request's elapsed milliseconds. A socket timeout or HTTP 408/504 is recorded as `timeout` and the next case continues; a stream that ends without `done` is `incomplete_stream`; authentication/authorization and other HTTP errors stop the run. Timeout and incomplete-stream records contain no exception text, prompts, SQL, answers, row values, or tokens. Custom datasets without a category are grouped as `unclassified`. To evaluate the two multi-turn follow-up chains with the same conversation IDs used across their turns, pass the dedicated dataset:

```bash
uv run --no-project python evaluate_agent.py --dataset agent_multiturn_questions.json
```

Entries with the same `conversation_group` share one generated conversation ID; ungrouped questions get independent IDs. The runner accepts HTTPS origins and loopback HTTP only, disables redirects, caps each event stream at 2 MiB, and prints case statuses plus hashes without prompts, SQL, answers, row values, group names, or tokens. This measures live ReAct tool-result accuracy on synthetic data; it does not certify production authorization or natural-language explanation quality. The current local API/service must include the structured SQL result event support described above.

The city refund-rate follow-up expects the complete authorized city result table (Guangzhou and Shenzhen); the final sentence identifies the highest city, but this exact-result scorecard does not judge prose semantics.

To run live prompt-policy probes for sensitive/cross-tenant requests and ambiguous questions, use:

```bash
uv run --no-project python evaluate_agent.py \
  --evaluation-type policy \
  --dataset agent_policy_cases.json
```

Policy cases pass only when the final response contains one of the case's configured refusal/clarification phrases, the API emitted no structured SQL result, and the SSE stream ends with `done`. The scorecard stores case status and a response hash, never the final text or prompt; it also reports separate deny and clarify accuracy plus their macro-average. This phrase-based benchmark checks a fixed synthetic policy set; it does not prove database-side authorization and should be reviewed alongside live traces and production RLS tests.

### Export DB-GPT spans over OTLP

DB-GPT already supports the OTLP gRPC exporter. Install the app's optional `observability` dependency group, enable it for the DB-GPT app process with `TRACER_TO_OPEN_TELEMETRY=true`, and point the standard OpenTelemetry exporter variables at a reachable collector:

```bash
TRACER_TO_OPEN_TELEMETRY=true \
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://otel-collector.example.com:4317 \
OTEL_EXPORTER_OTLP_TRACES_INSECURE=false \
dbgpt start webserver
```

The SQL execution spans use the request trace as their parent and export datasource/user metadata, SQL fingerprints, duration, row counts, and status; they do not include SQL text or bind values. The app also retains its local trace stores. A loopback OTLP gRPC collector round-trip is covered by the Core tracer tests; the endpoint above must be replaced by the deployment's collector address.

Sample integration (the allowed tables must come from authenticated business permissions, **not** from the LLM):

```python
from guarded_query import GuardedSQLiteQuery

service = GuardedSQLiteQuery(
    "/srv/data/sales.sqlite",
    allowed_tables={"orders", "order_items"},
    max_rows=100,
)
result = service.run("SELECT COUNT(*) AS total_orders FROM orders")
```

## Scope and follow-up

This example intentionally supports **SQLite only**. Its tenant and region IDs come from the server-verified `UserRequest` dependency and are never accepted from the query body. The fixture identities, tenant IDs, region IDs, and SQLite authorizer are demonstration policy, not production authorization.

PostgreSQL/MySQL need separate database-specific implementations using restrictive read-only credentials, dialect-aware validation, statement timeouts, grants and tenant row policies. Do not port SQLite authorizer assumptions to those engines. Query timeouts in-process are defense in depth, not a substitute for an isolated database server.
