"""Application service that converts graph state into API responses."""

import logging
import time

from app.agents.workflow import AgentWorkflow
from app.schemas.agent import (
    AgentNodeTraceResponse,
    AgentRunResponse,
    AgentToolCallResponse,
)
from app.schemas.chat import TokenUsage
from app.schemas.rag import RagSourceResponse

logger = logging.getLogger(__name__)


class AgentService:
    """Execute the LangGraph workflow for one user request."""

    def __init__(self, workflow: AgentWorkflow) -> None:
        self._workflow = workflow

    async def run(
        self,
        *,
        message: str,
        conversation_id: str | None,
    ) -> AgentRunResponse:
        started_at = time.perf_counter()
        state = await self._workflow.run(
            message=message,
            conversation_id=conversation_id,
        )
        latency_ms = (time.perf_counter() - started_at) * 1000
        usage_parts = state.get("usage_parts", [])
        usage = TokenUsage(
            prompt_tokens=sum(part.prompt_tokens for part in usage_parts),
            completion_tokens=sum(
                part.completion_tokens for part in usage_parts
            ),
        ) if usage_parts else None
        ticket_state = state.get("ticket_draft")
        trace = [
            AgentNodeTraceResponse(
                node=item["node"],
                duration_ms=item["duration_ms"],
                status=item["status"],
                error=item.get("error"),
            )
            for item in state.get("node_traces", [])
        ]
        tool_calls = [
            AgentToolCallResponse(
                tool_call_id=item["tool_call_id"],
                name=item["name"],
                status=item["status"],
                duration_ms=item["duration_ms"],
                error=item.get("error"),
            )
            for item in state.get("tool_calls", [])
        ]
        result = AgentRunResponse(
            intent=state.get("intent", "clarification"),
            status=state.get("status", "needs_clarification"),
            answer=state.get("answer"),
            ticket_draft=ticket_state,
            sources=state.get("sources", []),
            executed_nodes=state.get("executed_nodes", []),
            supervisor_reason=state.get("supervisor_reason", ""),
            model=state.get("model"),
            usage=usage,
            error=state.get("error"),
            latency_ms=round(latency_ms, 2),
            node_traces=trace,
            tool_calls=tool_calls,
            conversation_id=conversation_id,
            memory_persisted=False,
        )
        logger.info(
            "Agent run completed intent=%s status=%s nodes=%s latency_ms=%.2f",
            result.intent,
            result.status,
            ",".join(result.executed_nodes),
            latency_ms,
        )
        return result

