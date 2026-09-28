# Align database ReAct turn instructions with the core template

## Background

The database-mode workflow prompt now uses the core `terminate` `result` field, but still describes only `Thought -> Action -> Action Input`. `ToolCallingReActAgent` requires each turn to include `Action Intention` and `Action Reason`; its terminate form also requires `Phase: 返回最终结果`. These instructions still conflict and the local Qwen3 4B live request continued looping without completing.

## Goal

Make database-mode instructions express the same ReAct turn format the agent parser requires, so the model receives one consistent protocol for SQL and final-answer actions.

## Scope

- Includes: update the database workflow prompt and add a regression for required action fields and terminate phase/result format.
- Excludes: changing parsers, native tool calling, retry budgets, unrelated chat modes, SQL policies, and production settings.

## Acceptance criteria

- **AC-01:** Database-mode prompt tells the model to provide Thought, Action Intention, Action Reason, Action and Action Input for each turn; `terminate` includes the required final Phase and `{"result": ...}` schema.
- **AC-02:** Focused prompt and ReAct lifecycle tests pass.

## Approval basis

The user authorized fixing this DB-GPT conversation failure and completing the roadmap without repeated confirmation. The edit is confined to the already identified prompt conflict and its regression test.
