# Tasks: App-Agent and AWEL daily token quota

## T001: Meter App-Agent managed LLM calls

- Acceptance criteria: verified quota context is wrapped at the per-request Agent client and propagated through controller layers.
- Status: completed

## T002: Integrate AWEL request scope safely

- Acceptance criteria: AWEL routes without a trusted quota identity fail closed when quota is enabled; routes remain available when quota is disabled.
- Status: completed for HTTP chat flows, v1 domain knowledge flows, `/flow/debug`, and all dynamically registered `HttpTrigger` routes. No AWEL route is claimed as metered.

## T003: Verify and document supported boundaries

- Acceptance criteria: App-Agent, AWEL, prompt-template debug fail-closed, and Core wrapper regressions pass; roadmap states provider hard caps and other unsupported model endpoints are still outstanding.
- Status: completed

## T004: Fail closed on unmetered model endpoints and nested calls

- Acceptance criteria: unmetered knowledge summary, LLM-backed Tree/Hybrid or KnowledgeGraph retrieval, KnowledgeGraph indexing, Serve evaluation, LLM benchmark execution, and the volatility sub-agent reject before model invocation/task scheduling whenever either daily quota setting is enabled, because they do not have a trusted tenant/user quota context. Pure VectorStore retrieval and embedding indexing remain available.
- Status: completed
