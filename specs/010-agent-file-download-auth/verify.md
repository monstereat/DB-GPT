# Verification: Agent file download authorization

- `PYTHONPATH=packages/dbgpt-app/src:packages/dbgpt-serve/src:packages/dbgpt-core/src:packages/dbgpt-client/src:packages/dbgpt-ext/src .venv/bin/python -m pytest -q --import-mode=importlib -o addopts='' packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agent_file_download_auth.py` — 8 passed.
- `.venv/bin/ruff check packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agent_file_download_auth.py` — passed.
- `.venv/bin/ruff format --check packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agent_file_download_auth.py` — passed.
- `.venv/bin/python -m compileall -q packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/agentic_data_api.py packages/dbgpt-app/src/dbgpt_app/openapi/api_v1/tests/test_agent_file_download_auth.py` — passed.
- `git diff --check` — passed.
