import json
import logging
import os
from concurrent.futures import Executor
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator, Optional, Type, Union

from dbgpt.core import MessageConverter, ModelMetadata, ModelOutput, ModelRequest
from dbgpt.core.awel.flow import (
    TAGS_ORDER_HIGH,
    ResourceCategory,
    auto_register_resource,
)
from dbgpt.core.interface.parameter import LLMDeployModelParameters
from dbgpt.model.proxy.base import (
    AsyncGenerateStreamFunction,
    GenerateStreamFunction,
    ProxyLLMClient,
    register_proxy_model_adapter,
)
from dbgpt.model.proxy.llms.proxy_model import ProxyModel, parse_model_request
from dbgpt.util.i18n_utils import _

from ...utils.parse_utils import (
    parse_chat_message,
)

logger = logging.getLogger(__name__)


@auto_register_resource(
    label=_("Ollama Proxy LLM"),
    category=ResourceCategory.LLM_CLIENT,
    tags={"order": TAGS_ORDER_HIGH},
    description=_("Ollama proxy LLM configuration."),
    documentation_url="https://ollama.com/library",
    show_in_ui=False,
)
@dataclass
class OllamaDeployModelParameters(LLMDeployModelParameters):
    """Deploy model parameters for Ollama."""

    provider: str = "proxy/ollama"

    api_base: Optional[str] = field(
        default="${env:OLLAMA_API_BASE:-http://localhost:11434}",
        metadata={
            "help": _("The base url of the Ollama API."),
        },
    )


async def ollama_generate_stream(
    model: ProxyModel, tokenizer, params, device, context_len=4096
):
    client: OllamaLLMClient = model.proxy_llm_client
    request = parse_model_request(params, client.default_model, stream=True)
    stream = client.async_generate_stream(request)
    try:
        async for r in stream:
            yield r
    finally:
        await stream.aclose()


class OllamaLLMClient(ProxyLLMClient):
    def __init__(
        self,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        model_alias: Optional[str] = "llama2",
        context_length: Optional[int] = 4096,
        executor: Optional[Executor] = None,
    ):
        if not model:
            model = "llama2"
        if not api_base:
            api_base = "http://localhost:11434"
        self._model = model
        self._api_base = self._resolve_env_vars(api_base)

        super().__init__(
            model_names=[model, model_alias],
            context_length=context_length,
            executor=executor,
        )

    @classmethod
    def new_client(
        cls,
        model_params: OllamaDeployModelParameters,
        default_executor: Optional[Executor] = None,
    ) -> "OllamaLLMClient":
        return cls(
            model=model_params.real_provider_model_name,
            api_base=model_params.api_base,
            model_alias=model_params.real_provider_model_name,
            context_length=model_params.context_length,
            executor=default_executor,
        )

    @classmethod
    def param_class(cls) -> Type[OllamaDeployModelParameters]:
        return OllamaDeployModelParameters

    @classmethod
    def generate_stream_function(
        cls,
    ) -> Optional[Union[GenerateStreamFunction, AsyncGenerateStreamFunction]]:
        return ollama_generate_stream

    @property
    def default_model(self) -> str:
        return self._model

    def sync_generate_stream(
        self,
        request: ModelRequest,
        message_converter: Optional[MessageConverter] = None,
    ) -> Iterator[ModelOutput]:
        try:
            import ollama
            from ollama import ChatResponse, Client
        except ImportError as e:
            raise ValueError(
                "Could not import python package: ollama "
                "Please install ollama by command `pip install ollama"
            ) from e
        request = self.local_covert_message(request, message_converter)
        messages = request.to_common_messages()

        model = request.model or self._model
        if (
            model.lower().startswith("qwen3")
            and os.getenv("DBGPT_OLLAMA_DISABLE_THINKING", "false").lower()
            == "true"
            and messages
            and isinstance(messages[-1], dict)
            and isinstance(messages[-1].get("content"), str)
        ):
            messages[-1]["content"] += "\n/no_think"
        is_reasoning_model = getattr(request.context, "is_reasoning_model", False)
        options = {
            key: value
            for key, value in {
                "num_predict": request.max_new_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "stop": request.stop,
                "num_ctx": request.context_len,
            }.items()
            if value is not None
        }
        client = Client(self._api_base)
        try:
            chat_args = {
                "model": model,
                "messages": messages,
                "tools": request.tools,
                "options": options or None,
                "stream": request.stream,
            }
            disable_thinking = (
                model.lower().startswith("qwen3")
                and os.getenv("DBGPT_OLLAMA_DISABLE_THINKING", "false").lower()
                == "true"
            )
            if disable_thinking:
                # ollama-python 0.4.7 omits the API's `think` field from
                # Client.chat; preserve SDK streaming/error handling while
                # adding the server-supported Qwen3 switch to the payload.
                stream = client._request(
                    ChatResponse,
                    "POST",
                    "/api/chat",
                    json={**chat_args, "think": False},
                    stream=request.stream,
                )
            else:
                stream = client.chat(**chat_args)
            content = ""
            tool_calls = None
            for chunk in stream:
                message = chunk["message"]
                message_content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                content += message_content or ""
                raw_tool_calls = (
                    message.get("tool_calls")
                    if isinstance(message, dict)
                    else getattr(message, "tool_calls", None)
                )
                if raw_tool_calls:
                    tool_calls = []
                    for call in raw_tool_calls:
                        function = (
                            call.get("function")
                            if isinstance(call, dict)
                            else getattr(call, "function", None)
                        )
                        if not function:
                            continue
                        name = (
                            function.get("name")
                            if isinstance(function, dict)
                            else getattr(function, "name", None)
                        )
                        arguments = (
                            function.get("arguments", {})
                            if isinstance(function, dict)
                            else getattr(function, "arguments", {})
                        )
                        if not name:
                            continue
                        tool_calls.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": (
                                        json.dumps(arguments, ensure_ascii=False)
                                        if isinstance(arguments, dict)
                                        else arguments
                                    ),
                                },
                            }
                        )
                msg = parse_chat_message(content, extract_reasoning=is_reasoning_model)
                yield ModelOutput.build(
                    text=msg.content,
                    thinking=msg.reasoning_content,
                    error_code=0,
                    tool_calls=tool_calls,
                )
        except ollama.ResponseError as e:
            yield ModelOutput.build(
                text=f"**Ollama Response Error, Please CheckErrorInfo.**: {e}",
                error_code=-1,
            )

    async def async_generate_stream(
        self,
        request: ModelRequest,
        message_converter: Optional[MessageConverter] = None,
    ) -> AsyncIterator[ModelOutput]:
        """Stream asynchronously so request cancellation reaches Ollama."""
        try:
            import ollama
            from ollama import AsyncClient, ChatResponse
        except ImportError as e:
            raise ValueError(
                "Could not import python package: ollama "
                "Please install ollama by command `pip install ollama"
            ) from e

        request = self.local_covert_message(request, message_converter)
        messages = request.to_common_messages()
        model = request.model or self._model
        disable_thinking = (
            model.lower().startswith("qwen3")
            and os.getenv("DBGPT_OLLAMA_DISABLE_THINKING", "false").lower()
            == "true"
        )
        if (
            disable_thinking
            and messages
            and isinstance(messages[-1], dict)
            and isinstance(messages[-1].get("content"), str)
        ):
            messages[-1]["content"] += "\n/no_think"

        is_reasoning_model = getattr(request.context, "is_reasoning_model", False)
        options = {
            key: value
            for key, value in {
                "num_predict": request.max_new_tokens,
                "temperature": request.temperature,
                "top_p": request.top_p,
                "stop": request.stop,
                "num_ctx": request.context_len,
            }.items()
            if value is not None
        }
        client = AsyncClient(self._api_base)
        stream = None
        try:
            chat_args = {
                "model": model,
                "messages": messages,
                "tools": request.tools,
                "options": options or None,
                "stream": request.stream,
            }
            if disable_thinking:
                # ollama-python 0.4.7's chat method omits the API's `think` field.
                stream = await client._request(
                    ChatResponse,
                    "POST",
                    "/api/chat",
                    json={**chat_args, "think": False},
                    stream=request.stream,
                )
            else:
                stream = await client.chat(**chat_args)

            content = ""
            tool_calls = None
            async for chunk in stream:
                message = (
                    chunk.get("message")
                    if isinstance(chunk, dict)
                    else getattr(chunk, "message", None)
                )
                message_content = (
                    message.get("content")
                    if isinstance(message, dict)
                    else getattr(message, "content", None)
                )
                content += message_content or ""
                raw_tool_calls = (
                    message.get("tool_calls")
                    if isinstance(message, dict)
                    else getattr(message, "tool_calls", None)
                )
                if raw_tool_calls:
                    tool_calls = []
                    for call in raw_tool_calls:
                        function = (
                            call.get("function")
                            if isinstance(call, dict)
                            else getattr(call, "function", None)
                        )
                        if not function:
                            continue
                        name = (
                            function.get("name")
                            if isinstance(function, dict)
                            else getattr(function, "name", None)
                        )
                        arguments = (
                            function.get("arguments", {})
                            if isinstance(function, dict)
                            else getattr(function, "arguments", {})
                        )
                        if not name:
                            continue
                        tool_calls.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": (
                                        json.dumps(arguments, ensure_ascii=False)
                                        if isinstance(arguments, dict)
                                        else arguments
                                    ),
                                },
                            }
                        )
                msg = parse_chat_message(content, extract_reasoning=is_reasoning_model)
                yield ModelOutput.build(
                    text=msg.content,
                    thinking=msg.reasoning_content,
                    error_code=0,
                    tool_calls=tool_calls,
                )
        except ollama.ResponseError as e:
            yield ModelOutput.build(
                text=f"**Ollama Response Error, Please CheckErrorInfo.**: {e}",
                error_code=-1,
            )
        finally:
            try:
                if stream is not None:
                    close_stream = getattr(stream, "aclose", None)
                    if close_stream:
                        await close_stream()
            finally:
                # ollama-python 0.4.7 has no public AsyncClient.close method.
                await client._client.aclose()


register_proxy_model_adapter(
    OllamaLLMClient,
    supported_models=[
        ModelMetadata(
            model="deepseek-v3",
            context_length=64 * 1024,
            max_output_length=8 * 1024,
            description="DeepSeek-V3 by DeepSeek",
            link="https://ollama.com/library/deepseek-v3",
            function_calling=True,
        ),
        ModelMetadata(
            model="deepseek-r1:671b",
            context_length=64 * 1024,
            max_output_length=8 * 1024,
            description="DeepSeek-R1 by DeepSeek",
            link="https://ollama.com/library/deepseek-r1",
            function_calling=True,
        ),
        # More models see: https://ollama.com/search
    ],
)
