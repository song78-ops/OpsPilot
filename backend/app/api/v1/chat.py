"""Non-streaming chat endpoint."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service
from app.api.sse import encode_sse_event
from app.core.exceptions import ApplicationError
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse:
    """Answer a single user message with DeepSeek."""
    return await service.answer(payload.message)


@router.post(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            }
        }
    },
)
async def chat_stream(
    payload: ChatRequest,
    request: Request,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    """Stream an answer as Server-Sent Events."""
    request_id = uuid.uuid4().hex

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in service.stream_answer(
                payload.message,
                request_id=request_id,
            ):
                if await request.is_disconnected():
                    logger.info(
                        "SSE client disconnected request_id=%s",
                        request_id,
                    )
                    return
                yield encode_sse_event(event)
        except asyncio.CancelledError:
            logger.info("SSE request canceled request_id=%s", request_id)
            raise
        except ApplicationError as exc:
            logger.warning(
                "SSE generation failed request_id=%s code=%s",
                request_id,
                exc.code,
            )
            yield encode_sse_event(
                ChatStreamEvent(
                    event="error",
                    data={
                        "request_id": request_id,
                        "code": exc.code,
                        "message": exc.message,
                    },
                )
            )
        except Exception as exc:
            logger.error(
                "Unexpected SSE failure request_id=%s type=%s",
                request_id,
                type(exc).__name__,
            )
            yield encode_sse_event(
                ChatStreamEvent(
                    event="error",
                    data={
                        "request_id": request_id,
                        "code": "STREAM_INTERNAL_ERROR",
                        "message": "The response stream was interrupted.",
                    },
                )
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )

