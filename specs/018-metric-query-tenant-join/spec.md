# Correct metric tenant joins and route regional sales deterministically

## Goal

Make the published regional sales query use tenant-safe composite joins and prevent the screenshot question from falling back to hand-written SQL.

## Evidence

The previous live q01 trace showed free SQL omitted `orders.status='completed'`, returning incorrect regional totals. Inspection also found metric compiler joins between refunds/orders and regions/orders used non-composite identifiers without `tenant_id`.

## Scope

- Fix tenant composite joins in published metric SQL compilation.
- For the known ecommerce-demo regional sales intent, expose only `metric_query` (plus terminate), with the published `sales_amount` metric and explicit quarter parameters.
- Add compiler and intent-routing regression tests; run q01 live.

## Acceptance criteria

- **AC-01:** Refund/order and order/region joins in compiled metric SQL include `tenant_id` and preserve the metric's completed-order filter.
- **AC-02:** The ecommerce-demo regional sales intent receives only the deterministic metric query tool; other database questions retain the catalog, metric query, and read-only SQL tools.
- **AC-03:** The screenshot q01 produces structured results matching gold, or the remaining exact failure is recorded.

## Approval basis

The user authorized repairing this local DB-GPT issue and proceeding without repeated confirmation. The change is based on the live q01 trace and source inspection; it does not alter data or database schema.
