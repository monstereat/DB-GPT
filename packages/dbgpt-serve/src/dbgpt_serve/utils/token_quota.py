"""Helpers for safely handling unmetered model calls when quotas are enabled."""

import json
import os

from fastapi import HTTPException


def daily_token_quota_enabled() -> bool:
    """Return whether either supported daily token quota setting is enabled."""
    return any(
        os.getenv(name, "").strip()
        for name in ("DBGPT_DAILY_TOKEN_LIMIT", "DBGPT_REACT_DAILY_TOKEN_LIMIT")
    )


def reject_unmetered_model_call(capability: str) -> None:
    """Fail closed when daily quotas are enabled but no quota identity is available."""
    if daily_token_quota_enabled():
        raise HTTPException(
            status_code=503,
            detail=f"Daily token quota is not available for {capability}",
        )


def knowledge_retrieval_may_call_llm(space) -> bool:
    """Detect retrieval strategies that can use generation or a knowledge graph."""
    if getattr(space, "vector_type", None) == "KnowledgeGraph":
        return True
    context = getattr(space, "context", None)
    if not context:
        return False
    try:
        parsed = json.loads(context) if isinstance(context, str) else context
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict):
        return False
    embedding = parsed.get("embedding")
    if not isinstance(embedding, dict):
        return False
    return embedding.get("retrieve_mode") in {"Tree", "HYBRID"}
