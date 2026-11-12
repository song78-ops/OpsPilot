"""Agent workflow API schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.state import AgentIntent, AgentStatus
from app.schemas.chat import TokenUsage
from app.schemas.rag import RagSourceResponse
from app.schemas.ticket import TicketDraftResponse


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4_000)
    conversation_id: str | None = Field(default=None, max_length=128)


class AgentNodeTraceResponse(BaseModel):
    node: str
    duration_ms: float
    status: str
    error: str | None = None


class AgentToolCallResponse(BaseModel):
    tool_call_id: str
    name: str
    status: str
    duration_ms: float
    error: str | None = None


class AgentRunResponse(BaseModel):
    intent: AgentIntent
    status: AgentStatus
    answer: str | None
    ticket_draft: TicketDraftResponse | None
    sources: list[RagSourceResponse]
    executed_nodes: list[str]
    supervisor_reason: str
    model: str | None
    usage: TokenUsage | None
    error: str | None
    latency_ms: float
    node_traces: list[AgentNodeTraceResponse]
    tool_calls: list[AgentToolCallResponse]
    conversation_id: str | None
    memory_persisted: Literal[False] = False

