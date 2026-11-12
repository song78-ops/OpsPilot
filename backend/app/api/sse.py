"""Encoding helpers for Server-Sent Events."""

import json

from app.schemas.chat import ChatStreamEvent


def encode_sse_event(event: ChatStreamEvent) -> str:
    """Encode one domain event using the text/event-stream wire format."""
    data = json.dumps(
        event.data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event.event}\ndata: {data}\n\n"

