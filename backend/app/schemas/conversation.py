"""Conversation history API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ConversationMessageResponse(BaseModel):
    id: int
    role: Literal["user", "assistant", "tool"]
    content: str
    intent: str | None
    status: str | None
    tool_name: str | None
    tool_status: str | None
    business_reference_id: str | None
    created_at: datetime


class ConversationHistoryResponse(BaseModel):
    conversation_id: str
    created_at: datetime
    updated_at: datetime
    last_ticket_draft_id: str | None
    ticket_references: list[str]
    total: int
    messages: list[ConversationMessageResponse]
    memory_persisted: Literal[True] = True


class ConversationSummaryResponse(BaseModel):
    conversation_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    total: int
    limit: int
    offset: int
