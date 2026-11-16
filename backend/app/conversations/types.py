"""Conversation memory records and model context values."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from app.schemas.ticket import TicketDraftResponse

ConversationRole = Literal["user", "assistant", "tool"]
AgentRequestStatus = Literal["in_progress", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class AgentRequestRecord:
    request_key: str
    request_id: str | None
    request_summary: str | None
    fingerprint: str
    conversation_id: str | None
    status: AgentRequestStatus
    response_json: str | None
    error_code: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime


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
