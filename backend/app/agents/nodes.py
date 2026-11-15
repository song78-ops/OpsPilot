"""LangGraph node implementations for routing and response generation."""

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agents.state import (
    AgentIntent,
    AgentNodeTrace,
    AgentState,
)
from app.core.exceptions import ApplicationError
from app.llm.base import LLMProvider, LLMToolCall
from app.rag.exceptions import AgentNodeExecutionError
from app.rag.qa.service import RagQAService
from app.rag.retrieval.types import SearchMode
from app.schemas.chat import TokenUsage
from app.services.chat_service import ChatService
from app.tools.ticket_tools import (
    TICKET_TOOL_DEFINITIONS,
    TicketToolExecutor,
    ToolExecutionOutcome,
)

logger = logging.getLogger(__name__)


class SupervisorDecision(BaseModel):
    intent: AgentIntent
    reason: str
    clarification_question: str = ""


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("No JSON object found")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Structured output is not an object")
    return payload


def _trace(
    node: str,
    started_at: float,
    *,
    status: str,
    error: str | None = None,
) -> AgentNodeTrace:
    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "Agent node completed node=%s status=%s duration_ms=%.2f error=%s",
        node,
        status,
        duration_ms,
        error or "none",
    )
    return AgentNodeTrace(
        node=node,
        duration_ms=duration_ms,
        status=status,
        error=error,
    )


class AgentNodes:
    """Dependencies and node functions used by the StateGraph."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        rag_service: RagQAService,
        chat_service: ChatService,
        ticket_tool_executor: TicketToolExecutor,
        supervisor_prompt: str,
        ticket_prompt: str,
        max_tool_calls: int,
    ) -> None:
        self._llm = llm
        self._rag_service = rag_service
        self._chat_service = chat_service
        self._ticket_tool_executor = ticket_tool_executor
        self._supervisor_prompt = supervisor_prompt
        self._ticket_prompt = ticket_prompt
        self._max_tool_calls = max_tool_calls

    @property
    def max_tool_calls(self) -> int:
        return self._max_tool_calls

    async def supervisor(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            result = await self._llm.generate(
                system_prompt=self._supervisor_prompt,
                user_message=self._request_with_history(state),
            )
            decision = SupervisorDecision.model_validate(
                _parse_json_object(result.content)
            )
            update: dict[str, Any] = {
                "intent": decision.intent,
                "supervisor_reason": decision.reason,
                "clarification_question": decision.clarification_question,
                "model": result.model,
                "executed_nodes": ["supervisor"],
                "node_traces": [
                    _trace("supervisor", started_at, status=decision.intent)
                ],
                "usage_parts": [
                    TokenUsage(
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                    )
                ],
            }
            if decision.intent == "ticket_request":
                update["ticket_messages"] = [
                    {"role": "user", "content": state["message"]}
                ]
                update["ticket_tool_call_count"] = 0
            return update
        except ApplicationError as exc:
            logger.warning(
                "Supervisor model error code=%s",
                exc.code,
            )
            raise
        except (ValueError, ValidationError, json.JSONDecodeError):
            logger.warning(
                "Supervisor returned invalid structured output; "
                "routing to clarification"
            )
            return self._supervisor_fallback(
                started_at,
                error="SUPERVISOR_INVALID_OUTPUT",
                reason="意图识别结果无效。",
            )
        except Exception as exc:
            logger.error(
                "Supervisor node failed type=%s",
                type(exc).__name__,
            )
            return self._supervisor_fallback(
                started_at,
                error="SUPERVISOR_NODE_ERROR",
                reason="意图识别节点发生异常。",
            )

    def _supervisor_fallback(
        self,
        started_at: float,
        *,
        error: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "intent": "clarification",
            "supervisor_reason": reason,
            "clarification_question": (
                "请补充说明你希望查询企业知识、创建故障工单，"
                "还是进行普通聊天。"
            ),
            "error": error,
            "executed_nodes": ["supervisor"],
            "node_traces": [
                _trace(
                    "supervisor",
                    started_at,
                    status="clarification",
                    error=error,
                )
            ],
        }

    async def knowledge(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            result = await self._rag_service.ask(
                query=state["message"],
                top_k=None,
                mode=SearchMode.HYBRID,
                rerank=False,
                candidate_k=None,
                document_id=None,
            )
        except ApplicationError as exc:
            logger.warning(
                "Knowledge node failed code=%s",
                exc.code,
            )
            raise
        except Exception as exc:
            logger.error(
                "Knowledge node failed type=%s",
                type(exc).__name__,
            )
            raise AgentNodeExecutionError("knowledge") from exc

        status = (
            "completed"
            if result.status == "answered"
            else "insufficient_evidence"
        )
        usage_parts = (
            [result.usage]
            if result.usage is not None
            else []
        )
        return {
            "status": status,
            "answer": result.answer,
            "sources": result.sources,
            "model": result.model or state.get("model"),
            "executed_nodes": ["knowledge"],
            "node_traces": [
                _trace("knowledge", started_at, status=status)
            ],
            "usage_parts": usage_parts,
        }

    async def chat(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        try:
            result = await self._chat_service.answer(
                state["message"],
                history_context=state.get("history_context", ""),
            )
        except ApplicationError as exc:
            logger.warning("Chat node failed code=%s", exc.code)
            raise
        except Exception as exc:
            logger.error("Chat node failed type=%s", type(exc).__name__)
            raise AgentNodeExecutionError("chat") from exc
        return {
            "status": "completed",
            "answer": result.answer,
            "sources": [],
            "model": result.model,
            "executed_nodes": ["chat"],
            "node_traces": [
                _trace("chat", started_at, status="completed")
            ],
            "usage_parts": [result.usage] if result.usage else [],
        }

    async def ticket_agent(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        messages = list(state.get("ticket_messages", []))
        if not messages:
            messages = [{"role": "user", "content": state["message"]}]
        system_context = self._ticket_system_context(state)
        try:
            result = await self._llm.generate_with_tools(
                messages=[
                    {"role": "system", "content": system_context},
                    *messages,
                ],
                tools=TICKET_TOOL_DEFINITIONS,
            )
        except ApplicationError as exc:
            logger.warning("Ticket agent model error code=%s", exc.code)
            raise
        except Exception as exc:
            logger.error(
                "Ticket agent failed type=%s",
                type(exc).__name__,
            )
            raise AgentNodeExecutionError("ticket_agent") from exc

        usage = TokenUsage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )
        if result.tool_calls:
            call_count = int(state.get("ticket_tool_call_count", 0))
            if call_count + len(result.tool_calls) > self._max_tool_calls:
                return {
                    "status": "needs_clarification",
                    "answer": (
                        "工单工具调用次数已达到限制。"
                        "请补充信息后重新发起请求。"
                    ),
                    "pending_tool_calls": [],
                    "model": result.model,
                    "error": "TOOL_CALL_LIMIT",
                    "executed_nodes": ["ticket_agent"],
                    "node_traces": [
                        _trace(
                            "ticket_agent",
                            started_at,
                            status="tool_call_limit",
                            error="TOOL_CALL_LIMIT",
                        )
                    ],
                    "usage_parts": [usage],
                }

            assistant_message = {
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments,
                        },
                    }
                    for call in result.tool_calls
                ],
            }
            return {
                "ticket_messages": [assistant_message],
                "pending_tool_calls": [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in result.tool_calls
                ],
                "ticket_tool_call_count": call_count,
                "model": result.model,
                "executed_nodes": ["ticket_agent"],
                "node_traces": [
                    _trace(
                        "ticket_agent",
                        started_at,
                        status="tool_calls_requested",
                    )
                ],
                "usage_parts": [usage],
            }

        tool_results = state.get("ticket_tool_results", [])
        if tool_results:
            outcome = ToolExecutionOutcome.model_validate(tool_results[-1])
            if outcome.ok and outcome.draft is not None:
                status = "ticket_draft_ready"
                answer = outcome.message
                error = None
            elif outcome.status == "needs_more_info":
                status = "needs_clarification"
                answer = outcome.message
                error = outcome.error_code
            else:
                status = "needs_clarification"
                answer = f"工单草稿操作未成功：{outcome.message}"
                error = outcome.error_code
            draft = outcome.draft
        else:
            status = "needs_clarification"
            answer = result.content or (
                "请补充设备或系统名称、故障现象和期望处理方式。"
            )
            error = None
            draft = None

        return {
            "status": status,
            "answer": answer,
            "ticket_draft": draft,
            "model": result.model,
            "error": error,
            "pending_tool_calls": [],
            "executed_nodes": ["ticket_agent"],
            "node_traces": [
                _trace(
                    "ticket_agent",
                    started_at,
                    status=status,
                    error=error,
                )
            ],
            "usage_parts": [usage],
        }

    async def ticket_tools(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        pending_calls = state.get("pending_tool_calls", [])
        calls = [
            LLMToolCall(
                id=str(item["id"]),
                name=str(item["name"]),
                arguments=str(item["arguments"]),
            )
            for item in pending_calls
        ]
        tool_messages: list[dict] = []
        outcomes: list[dict] = []
        traces: list[AgentNodeTrace] = []
        tool_call_records: list[dict[str, Any]] = []
        trusted_value = state.get("trusted_ticket_draft_ids")
        trusted_ids = (
            list(trusted_value)
            if trusted_value is not None
            else None
        )

        for call in calls:
            call_started = time.perf_counter()
            outcome = await self._ticket_tool_executor.execute(
                call,
                conversation_id=state.get("conversation_id"),
                trusted_ticket_draft_ids=trusted_ids,
                ticket_target_ambiguous=state.get(
                    "ticket_target_ambiguous",
                    False,
                ),
                user_message=state["message"],
            )
            if (
                trusted_ids is not None
                and outcome.ok
                and outcome.draft is not None
            ):
                if outcome.draft.id not in trusted_ids:
                    trusted_ids.append(outcome.draft.id)
            outcomes.append(outcome.model_dump(mode="json"))
            tool_messages.append(
                self._ticket_tool_executor.tool_message(call, outcome)
            )
            traces.append(
                _trace(
                    f"tool:{call.name}",
                    call_started,
                    status=outcome.status,
                    error=outcome.error_code,
                )
            )
            tool_call_records.append(
                {
                    "tool_call_id": call.id,
                    "name": call.name,
                    "status": outcome.status,
                    "duration_ms": (
                        time.perf_counter() - call_started
                    ) * 1000,
                    "error": outcome.error_code,
                }
            )

        return {
            "ticket_messages": tool_messages,
            "ticket_tool_results": outcomes,
            "pending_tool_calls": [],
            **(
                {"trusted_ticket_draft_ids": trusted_ids}
                if trusted_ids is not None
                else {}
            ),
            "ticket_tool_call_count": (
                int(state.get("ticket_tool_call_count", 0)) + len(calls)
            ),
            "executed_nodes": ["ticket_tools"],
            "node_traces": [
                _trace(
                    "ticket_tools",
                    started_at,
                    status="completed",
                ),
                *traces,
            ],
            "tool_calls": tool_call_records,
            "usage_parts": [],
        }

    @staticmethod
    def _request_with_history(state: AgentState) -> str:
        history = state.get("history_context", "")
        history_block = f"{history}\n\n" if history else ""
        return (
            f"{history_block}"
            "<current_user_request>\n"
            f"{state['message']}\n"
            "</current_user_request>"
        )

    def _ticket_system_context(self, state: AgentState) -> str:
        parts = [self._ticket_prompt]
        if state.get("ticket_context"):
            parts.append(state["ticket_context"])
        if state.get("history_context"):
            parts.append(state["history_context"])
        return "\n\n".join(parts)

    async def clarification(self, state: AgentState) -> dict[str, Any]:
        started_at = time.perf_counter()
        answer = state.get("clarification_question") or (
            "请明确你想查询企业知识、创建故障工单，还是进行普通聊天。"
        )
        return {
            "status": "needs_clarification",
            "answer": answer,
            "sources": [],
            "ticket_draft": None,
            "executed_nodes": ["clarification"],
            "node_traces": [
                _trace(
                    "clarification",
                    started_at,
                    status="needs_clarification",
                )
            ],
            "usage_parts": [],
        }

