from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ..token_quota import (
    knowledge_retrieval_may_call_llm,
    reject_unmetered_model_call,
)


@pytest.mark.parametrize(
    "setting_name",
    ["DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT"],
)
def test_reject_unmetered_model_call_when_quota_is_enabled(monkeypatch, setting_name):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv(setting_name, "1000")

    with pytest.raises(HTTPException) as exc_info:
        reject_unmetered_model_call("example endpoint")

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == (
        "Daily token quota is not available for example endpoint"
    )


def test_allow_unmetered_model_call_when_quota_is_disabled(monkeypatch):
    monkeypatch.setenv("DBGPT_DAILY_TOKEN_LIMIT", "")
    monkeypatch.setenv("DBGPT_REACT_DAILY_TOKEN_LIMIT", "")

    reject_unmetered_model_call("example endpoint")


@pytest.mark.parametrize(
    "space, expected",
    [
        (SimpleNamespace(vector_type="KnowledgeGraph", context=None), True),
        (
            SimpleNamespace(
                vector_type="VectorStore",
                context='{"embedding":{"retrieve_mode":"Tree"}}',
            ),
            True,
        ),
        (
            SimpleNamespace(
                vector_type="VectorStore",
                context='{"embedding":{"retrieve_mode":"HYBRID"}}',
            ),
            True,
        ),
        (
            SimpleNamespace(
                vector_type="VectorStore",
                context='{"embedding":{"retrieve_mode":"SEMANTIC"}}',
            ),
            False,
        ),
        (SimpleNamespace(vector_type="VectorStore", context=None), False),
    ],
)
def test_knowledge_retrieval_llm_detection(space, expected):
    assert knowledge_retrieval_may_call_llm(space) is expected
