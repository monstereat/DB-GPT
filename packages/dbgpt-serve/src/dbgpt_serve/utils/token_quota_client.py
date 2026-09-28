"""Daily token metering for the ReAct model client."""

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from dbgpt.core import (
    LLMClient,
    ModelMetadata,
    ModelOutput,
    ModelRequest,
)
from dbgpt_serve.token_quota import TokenQuotaDao, TokenQuotaExceededError

logger = logging.getLogger(__name__)
_RESERVATION_HEARTBEAT_SECONDS = 60


class TokenQuotaConfigurationError(RuntimeError):
    """Raised when a metered model request cannot be bounded safely."""


def build_metered_llm_client_wrapper(
    token_quota_context: Optional[Dict[str, Any]],
):
    """Build a request-scoped wrapper from a server-verified quota context."""
    if token_quota_context is None:
        return None

    def wrap(llm_client):
        if isinstance(llm_client, MeteredLLMClient):
            return llm_client
        return MeteredLLMClient(llm_client, **token_quota_context)

    return wrap


def resolve_daily_token_quota_context(
    user_token, configured_limit: Optional[str], setting_name: str
) -> Optional[Dict[str, Any]]:
    """Build quota identity only from an authenticated OIDC request context."""
    if configured_limit is None or not configured_limit.strip():
        return None
    try:
        daily_limit_tokens = int(configured_limit)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail=f"{setting_name} must be a positive integer",
        ) from exc
    if daily_limit_tokens <= 0:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail=f"{setting_name} must be a positive integer",
        )
    from fastapi import HTTPException

    from dbgpt_serve.utils.auth import trusted_agent_execution_context

    identity = trusted_agent_execution_context(user_token)
    if not identity or not identity.get("tenant_id") or not identity.get("actor_id"):
        raise HTTPException(
            status_code=403,
            detail="Daily token quota requires a verified OIDC user and tenant",
        )
    return {
        "tenant_id": identity["tenant_id"],
        "user_id": identity["actor_id"],
        "daily_limit_tokens": daily_limit_tokens,
    }


def safe_token_quota_error(error: Exception) -> Optional[str]:
    """Return a fixed public message for quota errors, without leaking internals."""
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TokenQuotaExceededError):
            return "每日 Token 额度已用尽，请明天再试。"
        if isinstance(current, TokenQuotaConfigurationError):
            return "当前请求无法安全应用每日 Token 额度，请联系管理员。"
        current = getattr(current, "original_exception", None) or current.__cause__
    return None


class MeteredLLMClient(LLMClient):
    """Reserve a model-call upper bound, then settle from provider usage."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        tenant_id: str,
        user_id: str,
        daily_limit_tokens: int,
        dao: Optional[TokenQuotaDao] = None,
    ):
        if not tenant_id or not user_id:
            raise ValueError("A trusted tenant and user are required for quotas")
        if (
            not isinstance(daily_limit_tokens, int)
            or isinstance(daily_limit_tokens, bool)
            or daily_limit_tokens <= 0
        ):
            raise ValueError("daily_limit_tokens must be a positive integer")
        self._llm_client = llm_client
        self._tenant_id = tenant_id
        self._user_id = user_id
        self._daily_limit_tokens = daily_limit_tokens
        self._dao = dao or TokenQuotaDao()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm_client, name)

    async def generate(
        self, request: ModelRequest, message_converter=None
    ) -> ModelOutput:
        result = None
        async for result in self.generate_stream(request, message_converter):
            pass
        if result is None:
            raise RuntimeError("The model returned an empty stream")
        return result

    async def models(self) -> List[ModelMetadata]:
        return await self._llm_client.models()

    async def count_token(self, model: str, prompt: str) -> int:
        return await self._llm_client.count_token(model, prompt)

    async def covert_message(
        self, request: ModelRequest, message_converter=None
    ) -> ModelRequest:
        return await self._llm_client.covert_message(request, message_converter)

    @staticmethod
    def _usage_tokens(output: Optional[ModelOutput]) -> Optional[int]:
        if output is None:
            return None
        usage = output.usage or {}
        total = usage.get("total_tokens")
        if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            if (
                isinstance(prompt, int)
                and not isinstance(prompt, bool)
                and prompt >= 0
                and isinstance(completion, int)
                and not isinstance(completion, bool)
                and completion >= 0
            ):
                total = prompt + completion
        if (
            not isinstance(total, int) or isinstance(total, bool) or total <= 0
        ) and output.metrics is not None:
            total = output.metrics.total_tokens
        if isinstance(total, int) and not isinstance(total, bool) and total > 0:
            return total
        return None

    async def generate_stream(
        self, request: ModelRequest, message_converter=None
    ) -> AsyncIterator[ModelOutput]:
        max_new_tokens = request.max_new_tokens
        if (
            not isinstance(max_new_tokens, int)
            or isinstance(max_new_tokens, bool)
            or max_new_tokens <= 0
        ):
            raise TokenQuotaConfigurationError(
                "A positive max_new_tokens is required when daily token quotas "
                "are enabled"
            )
        messages = request.get_messages()
        if any(not isinstance(message.content, str) for message in messages):
            raise TokenQuotaConfigurationError(
                "Daily token budgets currently require text-only model messages"
            )
        prompt = json.dumps(
            {
                "messages": [
                    message.model_dump(exclude_none=True) for message in messages
                ],
                "tools": request.tools,
                "tool_choice": request.tool_choice,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            prompt_tokens = await self._llm_client.count_token(request.model, prompt)
        except Exception as exc:
            raise TokenQuotaConfigurationError(
                "Unable to count prompt tokens; refusing an unbounded model request"
            ) from exc
        if (
            not isinstance(prompt_tokens, int)
            or isinstance(prompt_tokens, bool)
            or prompt_tokens < 0
        ):
            raise TokenQuotaConfigurationError(
                "The model tokenizer returned an invalid prompt token count"
            )

        # Include a small allowance for provider message framing/tool-schema
        # tokenization differences in addition to the worker tokenizer count.
        reserved_tokens = prompt_tokens + max_new_tokens + 64
        reservation = await asyncio.to_thread(
            self._dao.reserve,
            self._tenant_id,
            self._user_id,
            reserved_tokens,
            self._daily_limit_tokens,
        )
        reported_usage: Optional[int] = None
        heartbeat_task = asyncio.create_task(
            self._heartbeat_reservation(reservation.reservation_id)
        )
        try:
            async for output in self._llm_client.generate_stream(
                request, message_converter
            ):
                usage_tokens = self._usage_tokens(output)
                if usage_tokens is not None:
                    reported_usage = usage_tokens
                yield output
        except BaseException:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            # The provider may have accepted and billed a request before an
            # error/disconnect. Keep the complete reservation as a safe bound.
            await asyncio.shield(
                asyncio.to_thread(
                    self._dao.settle, reservation.reservation_id, reserved_tokens
                )
            )
            raise
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        # Providers that omit usage are charged the reserved upper bound. Never
        # turn missing usage into zero or release a potentially billed request.
        await asyncio.to_thread(
            self._dao.settle,
            reservation.reservation_id,
            reserved_tokens if reported_usage is None else reported_usage,
        )

    async def _heartbeat_reservation(self, reservation_id: str) -> None:
        """Keep long-running active model calls from being recovered as stale."""
        while True:
            await asyncio.sleep(_RESERVATION_HEARTBEAT_SECONDS)
            try:
                active = await asyncio.to_thread(self._dao.heartbeat, reservation_id)
                if not active:
                    logger.warning(
                        "Token quota reservation heartbeat found no pending record"
                    )
                    return
            except Exception:
                # Recovery charges the full reservation, so a temporary
                # heartbeat failure cannot undercount provider usage.
                logger.exception("Unable to refresh token quota reservation lease")
