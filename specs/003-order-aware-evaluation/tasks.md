# Tasks: order-aware gold-result evaluation

## T001: Add per-question order semantics and result comparator

- Allowed files: paths listed in `plan.md`.
- Acceptance: AC-01 through AC-04.
- Evidence: 65 evaluator/demo tests passed; T001 scope gate passed.
- Status: done

## T002: Verify and record evidence

- Dependencies: T001.
- Operation: run evaluator and full offline regressions; update roadmap and verification note.
- Evidence: full suite `188 passed`; targeted rerun `65 passed`; Ruff check/format passed; README/roadmap updated; JSON/compile and `git diff --check` passed. Related isolated MySQL connector timeout/pool-reuse and tenant/region execution smokes passed.
- Status: done
