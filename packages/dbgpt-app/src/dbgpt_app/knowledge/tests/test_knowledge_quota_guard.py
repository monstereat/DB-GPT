from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dbgpt_app.knowledge import api
from dbgpt_app.knowledge.request.request import (
    DocumentRecallTestRequest,
    DocumentSummaryRequest,
)


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_document_summary_fails_closed_when_daily_quota_enabled(
    monkeypatch, setting_name
):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")

    async def should_not_generate_summary(*args, **kwargs):
        raise AssertionError("document summary must not call its model service")

    monkeypatch.setattr(
        api.knowledge_space_service, "document_summary", should_not_generate_summary
    )

    def require_verified_identity(*_args):
        raise HTTPException(status_code=403, detail="Verified OIDC identity required")

    monkeypatch.setattr(
        api, "resolve_daily_token_quota_context", require_verified_identity
    )

    with pytest.raises(HTTPException) as exc_info:
        await api.document_summary(
            DocumentSummaryRequest(doc_id=1, model_name="test", conv_uid="conv")
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_document_summary_passes_verified_quota_context(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "1000")
    quota_context = {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "daily_limit_tokens": 1000,
    }
    monkeypatch.setattr(
        api, "resolve_daily_token_quota_context", lambda *_args: quota_context
    )
    calls = []

    class _Chat:
        prompt_template = type("Prompt", (), {"stream_out": True})()

    async def document_summary(**kwargs):
        calls.append(kwargs)
        return _Chat()

    async def stream(*_args):
        yield "summary"

    monkeypatch.setattr(
        api.knowledge_space_service, "document_summary", document_summary
    )
    monkeypatch.setattr(api, "stream_generator", stream)

    response = await api.document_summary(
        DocumentSummaryRequest(doc_id=1, model_name="test", conv_uid="conv")
    )

    assert calls == [
        {
            "request": DocumentSummaryRequest(
                doc_id=1, model_name="test", conv_uid="conv"
            ),
            "token_quota_context": quota_context,
        }
    ]
    assert response.media_type == "text/plain"


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
@pytest.mark.asyncio
async def test_recall_test_fails_closed_for_llm_backed_space(monkeypatch, setting_name):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")
    monkeypatch.setattr(
        api.knowledge_space_service,
        "get_knowledge_space",
        lambda request: [
            SimpleNamespace(
                vector_type="VectorStore",
                context='{"embedding":{"retrieve_mode":"Tree"}}',
            )
        ],
    )

    async def should_not_retrieve(*args, **kwargs):
        raise AssertionError("LLM-backed retrieval must not run")

    monkeypatch.setattr(api.knowledge_space_service, "recall_test", should_not_retrieve)

    with pytest.raises(HTTPException) as exc_info:
        await api.recall_test("test-space", DocumentRecallTestRequest(question="test"))

    assert exc_info.value.status_code == 503
