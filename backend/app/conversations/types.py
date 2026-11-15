"""Conversation memory records and model context values."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.schemas.ticket import TicketDraftResponse

ConversationRole = Literal["user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: str
    created_at: datetime
    updated_at: datetime
    last_ticket_draft_id: str | None


@dataclass(frozen=True, slots=True)
class ConversationMessageRecord:
    id: int
    conversation_id: str
    role: ConversationRole
    content: str
    intent: str | None
    status: str | None
    tool_name: str | None
    tool_status: str | None
    business_reference_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationContext:
    conversation: ConversationRecord
    messages: list[ConversationMessageRecord]
    candidate_drafts: list[TicketDraftResponse]
    last_ticket_draft: TicketDraftResponse | None
    target_ambiguous: bool = False
    metadata: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResultRecord:
    tool_call_id: str
    name: str
    status: str
    ok: bool
    message: str
    draft_id: str | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ConversationHistory:
    conversation: ConversationRecord
    messages: list[ConversationMessageRecord]
    total: int


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    conversation: ConversationRecord
    title: str
