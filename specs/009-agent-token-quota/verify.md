# Verification: App-Agent and AWEL daily token quota

## Local checks

- `PYTHONPATH=packages/dbgpt-core/src .venv/bin/pytest -q packages/dbgpt-core/src/dbgpt/core/awel/tests/trigger/test_http_trigger_quota.py` — 8 passed. Covers chat/command triggers, quota enabled/disabled, both router and dynamic app registration, and verifies rejected requests do not call `_trigger_dag`.
- `.venv/bin/ruff check packages/dbgpt-core/src/dbgpt/core/awel/trigger/http_trigger.py packages/dbgpt-core/src/dbgpt/core/awel/tests/trigger/test_http_trigger_quota.py` — passed.
- `.venv/bin/ruff format --check packages/dbgpt-core/src/dbgpt/core/awel/trigger/http_trigger.py packages/dbgpt-core/src/dbgpt/core/awel/tests/trigger/test_http_trigger_quota.py` — passed.
- `PYTHONPATH=packages/dbgpt-core/src .venv/bin/python -m compileall -q packages/dbgpt-core/src/dbgpt/core/awel/trigger/http_trigger.py packages/dbgpt-core/src/dbgpt/core/awel/tests/trigger/test_http_trigger_quota.py` — passed.
- `git diff --check` — passed.

## Prompt template debug endpoint

- `PYTHONPATH=packages/dbgpt-serve/src:packages/dbgpt-core/src:packages/dbgpt-client/src uv run --no-project --with pytest python -m pytest -q --import-mode=importlib packages/dbgpt-serve/src/dbgpt_serve/prompt/tests/test_endpoints.py -k 'prompt_template_debug_fails_closed or prompt_template_debug_keeps_existing'` — 3 passed.
- Full Serve prompt test tree — 31 passed.
- The prompt template debug endpoint returns HTTP 503 before invoking the model when either daily token limit setting is enabled. The endpoint does not receive a trusted tenant/user quota context and is not metered; behavior remains available when both settings are unset.
- Ruff check passed for the endpoint; the existing prompt endpoint test module passes Ruff with its pre-existing `F811` fixture-name warnings ignored. Ruff format, `compileall`, and `git diff --check` passed.

The AWEL tests use a stub DAG executor. They verify local request gating, not live model execution, provider billing usage, or production quota behavior.

## Other unmetered model endpoints and RAG paths

- `uv run --no-sync python -m pytest -q -o addopts='' packages/dbgpt-serve/src/dbgpt_serve/utils/tests/test_token_quota.py packages/dbgpt-serve/src/dbgpt_serve/evaluate/api/tests/test_evaluate_quota_guard.py packages/dbgpt-app/src/dbgpt_app/knowledge/tests/test_knowledge_quota_guard.py packages/dbgpt-serve/src/dbgpt_serve/rag/tests/test_service.py packages/dbgpt-serve/src/dbgpt_serve/agent/agents/expand/tests/test_quota_guard.py packages/dbgpt-serve/src/dbgpt_serve/prompt/tests/test_endpoints.py` — 38 passed.
- Regression coverage verifies both quota settings reject knowledge summary, LLM-backed retrieval, KnowledgeGraph sync, volatility sub-agent, evaluation, and benchmark before service/model invocation or task scheduling. Pure semantic VectorStore retrieval and VectorStore document sync stay available. Prompt endpoint tests also passed.
- Ruff check and format check passed for touched Python files (`F811` ignored for pre-existing duplicate fixture/endpoint names in two touched modules). `compileall` and `git diff --check` passed.
- These guarded paths are unavailable while either quota setting is enabled; they fail closed and are not metered. Provider billing hard caps and custom AWEL/plugin model calls remain outside this quota mechanism.
