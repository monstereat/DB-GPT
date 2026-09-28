# Route published business metrics through the metric query tool

## Background

The local qwen3:1.7b ReAct run for the screenshot question generated an invalid column (`order_items.total_cents`) even though the database schema and business instructions identify `orders.total_cents`. It also returned a fabricated terminate answer before receiving a successful query result. A server-side metric catalog and deterministic metric compiler already exist, including `sales_amount` and its `region` dimension.

## Goal

Make database-mode questions that match a published business metric use the server-side metric catalog/query tools before falling back to hand-written SQL. This lets the server select approved columns and dimensions for known metrics.

## Scope

- Includes: expose role-filtered metric tools in database mode, instruct the Agent to use the published metric query path for catalogued metrics, and add a prompt/tool-availability regression.
- Excludes: changing SQL authorization, metric definitions, arbitrary NL-to-SQL behavior for uncatalogued requests, or Docker/model settings.

## Acceptance criteria

- **AC-01:** Database mode exposes the metric catalog and deterministic metric query tools to authorized users; the existing SQL tool remains available for other read-only queries.
- **AC-02:** Database-mode instructions direct published metric requests to the metric tools, and focused regressions pass.
- **AC-03:** The screenshot q01 query returns a structured result matching the fixed gold answer through the published `sales_amount` metric and `region` dimension, or the exact remaining failure is recorded.

## Approval basis

The user explicitly authorized repairing the DB-GPT screenshot failure and said to proceed using best judgment without repeated confirmation. Runtime logs now identify the invalid model-generated field and premature fabricated termination; routing published metrics through the existing trusted metric compiler is the smallest grounded fix.
