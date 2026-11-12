"""DeepSeek adapter using its OpenAI-compatible API."""

import inspect
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.core.exceptions import (
    ApplicationError,
    LLMConnectionError,
    LLMTimeoutError,
    LLMUpstreamError,
)
from app.llm.base import LLMResult, LLMStreamChunk

logger = logging.getLogger(__name__)


class DeepSeekLLM:
    """Generate chat completions through DeepSeek."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        temperature: float,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    async def generate(self, *, system_prompt: str, user_message: str) -> LLMResult:
        """Request one non-streaming completion from DeepSeek."""
        try:
            completion = await self._client.chat.completions.create(
                **self._request_kwargs(
                    system_prompt=system_prompt,
                    user_message=user_message,
                ),
                temperature=self._temperature,
            )
        except APIError as exc:
            raise self._translate_api_error(exc) from exc

        if not completion.choices:
            raise LLMUpstreamError("DeepSeek returned no completion choices.")

        content = completion.choices[0].message.content
        if not content:
            raise LLMUpstreamError("DeepSeek returned an empty response.")

        usage = completion.usage
        return LLMResult(
            content=content,
            model=completion.model or self._model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream incremental DeepSeek output without buffering the full answer."""
        upstream_stream: Any | None = None
        try:
            upstream_stream = await self._client.chat.completions.create(
                **self._request_kwargs(
                    system_prompt=system_prompt,
                    user_message=user_message,
                ),
                temperature=self._temperature,
                stream=True,
                stream_options={"include_usage": True},
            )

            async for chunk in upstream_stream:
                model = getattr(chunk, "model", None) or self._model
                choices = getattr(chunk, "choices", None) or []

                for choice in choices:
                    delta = getattr(choice, "delta", None)
                    text = getattr(delta, "content", None)
                    if text:
                        yield LLMStreamChunk(text=text, model=model)

                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    yield LLMStreamChunk(
                        model=model,
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens", None),
                    )
        except APIError as exc:
            raise self._translate_api_error(exc) from exc
        finally:
            await self._close_stream(upstream_stream)

    def _request_kwargs(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> dict[str, Any]:
        """Build common OpenAI-compatible request fields."""
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }

    @staticmethod
    def _translate_api_error(exc: APIError) -> ApplicationError:
        """Translate SDK exceptions without logging request credentials."""
        logger.warning("DeepSeek API error type=%s", type(exc).__name__)
        if isinstance(exc, APITimeoutError):
            return LLMTimeoutError()
        if isinstance(exc, APIConnectionError):
            return LLMConnectionError()
        if isinstance(exc, AuthenticationError):
            return LLMUpstreamError(
                "DeepSeek authentication failed. Check DEEPSEEK_API_KEY."
            )
        if isinstance(exc, RateLimitError):
            return LLMUpstreamError(
                "DeepSeek rate limit was reached. Try again later."
            )
        if isinstance(exc, APIStatusError):
            return LLMUpstreamError(
                f"DeepSeek returned an upstream error (HTTP {exc.status_code})."
            )
        return LLMUpstreamError()

    @staticmethod
    async def _close_stream(stream: Any | None) -> None:
        """Close an upstream stream if one was opened."""
        if stream is None:
            return
        close = getattr(stream, "close", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "Failed to close DeepSeek stream: type=%s",
                type(exc).__name__,
            )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()

