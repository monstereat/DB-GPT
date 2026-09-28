# Verification: order-aware gold-result evaluation

## Results

- Focused evaluator and fixture regression: `65 passed`.
- Full enterprise Text-to-SQL suite: `188 passed`.
- T001 and T002 scope gates: passed.
- `git diff --check`: passed.
- JSON metadata validation and Python compile: passed.
- Ruff check and format: passed.
- Isolated MySQL 8.4 connector smoke: canceled a bounded read query, classified error 3024 as timeout, then verified session timeout reset and pooled connection reuse.
- Isolated MySQL 8.4 tenant/region smoke: prepared queries with the DB-GPT App policy and executed them through the real connector; tenant and sales-region results matched the expected scope.

## Limits

The fixed benchmark is synthetic and still does not measure live model-generated SQL or open-ended semantic quality. The MySQL checks use temporary local containers; they do not prove production grants/RLS, enterprise identity deployment, or other driver behavior.
