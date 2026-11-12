"""Use cases for non-streaming and streaming questions."""

import inspect
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import ApplicationError
from app.llm.base import LLMProvider
from app.schemas.chat import ChatResponse, ChatStreamEvent, TokenUsage

logger = logging.getLogger(__name__)


class ChatService:
    """Coordinate prompt construction and model invocation."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        system_prompt: str,
        model_name: str = "unknown",
    ) -> None:
        self._llm = llm
        self._system_prompt = system_prompt
        self._model_name = model_name

    async def answer(self, message: str) -> ChatResponse:
        """Generate an answer for one user message."""
        result = await self._llm.generate(
            system_prompt=self._system_prompt,
            user_message=message,
        )
        return ChatResponse(
            answer=result.content,
            model=result.model,
            usage=TokenUsage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            ),
        )

    async def stream_answer(
        self,
        message: str,
        *,
        request_id: str,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Convert provider deltas into stable events for an HTTP SSE adapter."""
        yield ChatStreamEvent(
            event="meta",
            data={
                "request_id": request_id,
                "model": self._model_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        provider_stream = self._llm.stream(
            system_prompt=self._system_prompt,
            user_message=message,
        )
        try:
            async for chunk in provider_stream:
                if chunk.text:
                    yield ChatStreamEvent(
                        event="token",
                        data={"text": chunk.text},
                    )

                if (
                    chunk.prompt_tokens is not None
                    or chunk.completion_tokens is not None
                ):
                    yield ChatStreamEvent(
                        event="usage",
                        data={
                            "prompt_tokens": chunk.prompt_tokens or 0,
                            "completion_tokens": chunk.completion_tokens or 0,
                        },
                    )
        except ApplicationError as exc:
            logger.warning(
                "Chat stream failed request_id=%s code=%s",
                request_id,
                exc.code,
            )
            yield ChatStreamEvent(
                event="error",
                data={
                    "request_id": request_id,
                    "code": exc.code,
                    "message": exc.message,
                },
            )
            return
        except Exception as exc:
            logger.error(
                "Unexpected stream failure request_id=%s type=%s",
                request_id,
                type(exc).__name__,
            )
            yield ChatStreamEvent(
                event="error",
                data={
                    "request_id": request_id,
                    "code": "STREAM_INTERNAL_ERROR",
                    "message": "The response stream was interrupted.",
                },
            )
            return
        finally:
            await self._close_async_iterator(provider_stream)

        yield ChatStreamEvent(
            event="done",
            data={"request_id": request_id},
        )

    @staticmethod
    async def _close_async_iterator(iterator: Any) -> None:
        """Ensure a canceled HTTP request also closes the upstream stream."""
        close = getattr(iterator, "aclose", None)
        if close is None:
            return
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "Failed to close provider stream: type=%s",
                type(exc).__name__,
            )

