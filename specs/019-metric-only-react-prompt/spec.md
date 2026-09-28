# Align metric-only ReAct prompt with the restricted tool set

## Evidence

With only `metric_query` registered, qwen3:1.7b repeatedly emitted `Action: sql_query`; the existing generic prompt still required `sql_query`, so the parser rejected each attempt and no structured result was emitted.

## Goal and scope

When the ecommerce-demo regional sales request is restricted to `metric_query`, provide a matching metric-only ReAct format and explicit arguments. Preserve the existing generic database prompt for all other requests. Add focused regression and rerun q01.

## Acceptance criteria

- **AC-01:** Metric-only prompt names `metric_query` with its parameter schema and contains no `sql_query` action instruction; generic database prompt still exposes its SQL example.
- **AC-02:** Focused prompt/lifecycle/metric compiler tests pass.
- **AC-03:** q01 exact-matches gold or records the remaining failure.

## Approval basis

User already authorized repairing the screenshot issue and continuing without repeated confirmation. Runtime logs prove a direct contradiction between the registered tool set and prompt action example.
