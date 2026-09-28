# Order-aware gold-result evaluation

## Goal

Make fixed candidate SQL scoring compare result ordering only when the question's meaning requires it. Unordered relational results must still preserve row multiplicity.

## Scope

- Add explicit `order_sensitive` metadata to all 50 gold questions.
- Compare unordered answers as a multiset of complete rows; compare ordered answers positionally.
- Use the same comparator in candidate scoring and gold SQL self-evaluation.
- Keep column order exact and preserve security/result handling.

## Ordering decisions

- Ordered: q09 monthly sales, q14 monthly refunds, q45 monthly customer/order metrics (chronological series), q47 top-three products (rank order).
- Unordered: the remaining questions. In particular, grouped questions that merely ask “各地区/各品类是多少” do not request ranking even when the reference SQL happens to use `ORDER BY`; one-row scalar/maximum questions have no result-row ordering requirement.

## Acceptance criteria

- AC-01: A candidate with the correct rows in a different order passes for an unordered question.
- AC-02: A candidate with the correct row set in the wrong order fails for an order-sensitive question.
- AC-03: Multiset comparison distinguishes duplicate-row counts; all existing gold candidates remain correct.
- AC-04: Both evaluator entry points apply identical metadata and behavior; scorecards do not expose result values.

## Approval

- Status: approved under the user's active goal to complete remaining roadmap work and candidate SQL evaluation expansion.
- This is a local evaluation-only change; it does not alter query authorization, databases, application APIs, or production configuration.
