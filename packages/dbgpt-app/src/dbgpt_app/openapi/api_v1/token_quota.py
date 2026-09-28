"""Compatibility exports for the shared Serve token quota client."""

from dbgpt_serve.utils.token_quota_client import (
    MeteredLLMClient,
    TokenQuotaConfigurationError,
    build_metered_llm_client_wrapper,
    resolve_daily_token_quota_context,
    safe_token_quota_error,
)

__all__ = [
    "MeteredLLMClient",
    "TokenQuotaConfigurationError",
    "build_metered_llm_client_wrapper",
    "resolve_daily_token_quota_context",
    "safe_token_quota_error",
]
