# Plan: order-aware gold-result comparison

1. Mark all 50 question records with a boolean `order_sensitive`; only q09, q14, q45, and q47 are true based on question semantics.
2. Add one reusable result-row comparator: positional equality for ordered answers; `Counter(tuple(row))` multiset equality otherwise.
3. Apply the comparator in `evaluate_candidates` and `evaluate_gold_questions`.
4. Add tests for shuffled equivalent rows, wrong Top-3 order, duplicate multiplicity, metadata completeness, and existing gold-bundle accuracy.
5. Document the distinction in the example README and roadmap. Run targeted and full offline suites, JSON validation, scope gate, and `git diff --check`.

## Files

- `examples/enterprise-text2sql/gold_questions.json`
- `examples/enterprise-text2sql/evaluate_candidates.py`
- `examples/enterprise-text2sql/ecommerce_demo.py`
- `examples/enterprise-text2sql/test_evaluate_candidates.py`
- `examples/enterprise-text2sql/README.md`
- `docs/develop-me-roadmap.md`
- `specs/003-order-aware-evaluation/**`

## Risk

An incorrect metadata flag changes score meaning. Every flag is therefore explicit, reviewed from the question wording, and covered by tests for the ordered/unordered boundary.
