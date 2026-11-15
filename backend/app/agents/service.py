"""Application service that converts graph state into API responses."""

import logging
import time
from typing import Any

from app.agents.workflow import AgentWorkflow
from app.conversations.service import (
    ConversationMemoryService,
    format_history,
    ticket_context_text,
)
from app.conversations.types import ToolResultRecord
from app.core.exceptions import ApplicationError
from app.schemas.agent import (
    AgentNodeTraceResponse,
    AgentRunResponse,
    AgentToolCallResponse,
)
from app.schemas.chat import TokenUsage
from app.schemas.rag import RagSourceResponse
from app.tools.ticket_tools import ToolExecutionOutcome

logger = logging.getLogger(__name__)


class AgentService:
    """Execute the LangGraph workflow for one user request."""

    def __init__(
        self,
        workflow: AgentWorkflow,
        *,
        conversation_memory: ConversationMemoryService | None = None,
    ) -> None:
        self._workflow = workflow
        self._conversation_memory = conversation_memory

    async def run(
        self,
        *,
        message: str,
        conversation_id: str | None,
    ) -> AgentRunResponse:
        if self._conversation_memory is None:
            started_at = time.perf_counter()
            state = await self._workflow.run(
                message=message,
                conversation_id=conversation_id,
            )
            return self._response(
                state,
                conversation_id=conversation_id,
                started_at=started_at,
                memory_persisted=False,
            )

        conversation = await self._conversation_memory.begin_or_resume(
            conversation_id
        )
        async with self._conversation_memory.conversation_lock(
            conversation.id
        ):
            started_at = time.perf_counter()
            context = await self._conversation_memory.build_context(
                conversation
            )
            try:
                state = await self._workflow.run(
                    message=message,
                    conversation_id=conversation.id,
                    history_context=format_history(context.messages),
                    ticket_context=ticket_context_text(context),
                    trusted_ticket_draft_ids=[
                        draft.id for draft in context.candidate_drafts
                    ],
                    ticket_target_ambiguous=context.target_ambiguous,
                    last_ticket_draft_id=(
                        context.conversation.last_ticket_draft_id
                    ),
                )
            except ApplicationError as exc:
                try:
                    await self._conversation_memory.record_failure(
                        conversation_id=conversation.id,
                        user_content=message,
                        error_code=exc.code,
                    )
                except ApplicationError:
                    logger.exception(
                        "Failed to persist Agent failure conversation_id=%s",
                        conversation.id,
                    )
                raise

            tool_results = self._tool_result_records(state)
            successful_drafts = [
                result.draft_id
                for result in tool_results
                if result.ok and result.draft_id is not None
            ]
            last_ticket_draft_id = (
                successful_drafts[-1]
                if successful_drafts
                else context.conversation.last_ticket_draft_id
            )
            await self._conversation_memory.record_turn(
                conversation_id=conversation.id,
                user_content=message,
                assistant_content=(
                    state.get("answer")
                    or self._fallback_assistant_content(state)
                ),
                intent=state.get("intent"),
                status=state.get("status"),
                tool_results=tool_results,
                last_ticket_draft_id=last_ticket_draft_id,
            )
            return self._response(
                state,
                conversation_id=conversation.id,
                started_at=started_at,
                memory_persisted=True,
            )

    def _response(
        self,
        state: dict[str, Any],
        *,
        conversation_id: str | None,
        started_at: float,
        memory_persisted: bool,
    ) -> AgentRunResponse:
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
            memory_persisted=memory_persisted,
        )
        logger.info(
            "Agent run completed intent=%s status=%s nodes=%s latency_ms=%.2f",
            result.intent,
            result.status,
            ",".join(result.executed_nodes),
            latency_ms,
        )
        return result

    @staticmethod
    def _tool_result_records(
        state: dict[str, Any],
    ) -> list[ToolResultRecord]:
        outcomes = [
            ToolExecutionOutcome.model_validate(item)
            for item in state.get("ticket_tool_results", [])
        ]
        calls = state.get("tool_calls", [])
        records: list[ToolResultRecord] = []
        for index, outcome in enumerate(outcomes):
            call = calls[index] if index < len(calls) else {}
            records.append(
                ToolResultRecord(
                    tool_call_id=str(call.get("tool_call_id", "")),
                    name=str(call.get("name", "unknown_tool")),
                    status=outcome.status,
                    ok=outcome.ok,
                    message=outcome.message,
                    draft_id=(
                        outcome.draft.id
                        if outcome.ok and outcome.draft is not None
                        else None
                    ),
                    error_code=outcome.error_code,
                )
            )
        return records

    @staticmethod
    def _fallback_assistant_content(state: dict[str, Any]) -> str:
        status = state.get("status")
        if status == "insufficient_evidence":
            return "知识库证据不足，未生成企业事实回答。"
        if status == "needs_clarification":
            return "Agent 需要用户补充更多信息。"
        return "Agent 已完成请求。"

