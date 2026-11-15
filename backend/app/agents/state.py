"""Shared state for the OpsPilot LangGraph workflow."""

import operator
from typing import Annotated, Literal, TypedDict

from app.schemas.chat import TokenUsage
from app.schemas.rag import RagSourceResponse
from app.schemas.ticket import TicketDraftResponse

AgentIntent = Literal[
    "knowledge_query",
    "ticket_request",
    "general_chat",
    "clarification",
]
AgentStatus = Literal[
    "completed",
    "insufficient_evidence",
    "ticket_draft_ready",
    "needs_clarification",
]


class AgentNodeTrace(TypedDict):
    node: str
    duration_ms: float
    status: str
    error: str | None


class AgentToolCallRecord(TypedDict):
    tool_call_id: str
    name: str
    status: str
    duration_ms: float
    error: str | None


class AgentState(TypedDict, total=False):
    message: str
    conversation_id: str | None
    history_context: str
    ticket_context: str
    trusted_ticket_draft_ids: list[str] | None
    ticket_target_ambiguous: bool
    last_ticket_draft_id: str | None
    intent: AgentIntent
    status: AgentStatus
    supervisor_reason: str
    clarification_question: str
    answer: str | None
    sources: list[RagSourceResponse]
    ticket_draft: TicketDraftResponse | None
    ticket_messages: Annotated[list[dict], operator.add]
    pending_tool_calls: list[dict]
    ticket_tool_results: Annotated[list[dict], operator.add]
    ticket_tool_call_count: int
    model: str | None
    error: str | None
    executed_nodes: Annotated[list[str], operator.add]
    node_traces: Annotated[list[AgentNodeTrace], operator.add]
    tool_calls: Annotated[list[AgentToolCallRecord], operator.add]
    usage_parts: Annotated[list[TokenUsage], operator.add]

