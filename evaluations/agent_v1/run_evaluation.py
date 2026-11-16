"""Run OpsPilot Agent v1 intent and task evaluations."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
EVALUATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(EVALUATION_DIR))

from app.agents.nodes import AgentNodes  # noqa: E402
from app.agents.service import AgentService  # noqa: E402
from app.agents.workflow import AgentWorkflow  # noqa: E402
from app.approvals.runtime import (  # noqa: E402
    ApprovalRuntime,
    create_approval_runtime,
)
from app.conversations.repository import (  # noqa: E402
    SQLAlchemyConversationRepository,
)
from app.conversations.service import ConversationMemoryService  # noqa: E402
from app.conversations.types import ToolResultRecord  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.llm.base import LLMToolCall  # noqa: E402
from app.llm.deepseek import DeepSeekLLM  # noqa: E402
from app.schemas.approval import ApprovalDecisionRequest  # noqa: E402
from app.schemas.ticket import (  # noqa: E402
    CreateTicketDraftArgs,
    TicketDraftResponse,
)
from app.services.chat_service import ChatService  # noqa: E402
from app.tickets.repository import (  # noqa: E402
    SQLAlchemyTicketDraftRepository,
)
from app.tickets.service import TicketDraftService  # noqa: E402
from app.tools.ticket_tools import (  # noqa: E402
    CREATE_TICKET_DRAFT,
    GET_TICKET_DRAFT,
    UPDATE_TICKET_DRAFT,
    TicketToolExecutor,
    ToolExecutionOutcome,
)

from agent_metrics import (  # noqa: E402
    INTENTS,
    intent_metrics,
    markdown_report,
    task_category_counts,
    task_metrics,
)

INTENTS_PATH = EVALUATION_DIR / "data" / "intents_v1.json"
TASKS_PATH = EVALUATION_DIR / "data" / "tasks_v1.json"
RESULTS_DIR = EVALUATION_DIR / "results"
SUPERVISOR_PROMPT_PATH = (
    BACKEND_ROOT / "app" / "prompts" / "system" / "supervisor.txt"
)
CHAT_PROMPT_PATH = (
    BACKEND_ROOT / "app" / "prompts" / "system" / "chat_system.txt"
)
TICKET_PROMPT_PATH = (
    BACKEND_ROOT / "app" / "prompts" / "system" / "ticket_draft.txt"
)

SUCCESS_TOOL_STATUSES = frozenset({"created", "retrieved", "updated"})


class _UnusedRagService:
    async def ask(self, **_: Any) -> Any:
        raise RuntimeError(
            "RAG was unexpectedly selected in a ticket-only evaluation task."
        )


class _UnusedTicketTools:
    async def execute(self, *_: Any, **__: Any) -> Any:
        raise RuntimeError("Ticket tools should not be used by intent evaluation.")


@dataclass(slots=True)
class TaskContext:
    task: dict[str, Any]
    root: Path
    ticket_repository: SQLAlchemyTicketDraftRepository
    conversation_repository: SQLAlchemyConversationRepository
    ticket_service: TicketDraftService
    memory: ConversationMemoryService
    executor: TicketToolExecutor
    approval_runtime: ApprovalRuntime
    agent_service: AgentService
    conversation_id: str | None = None
    seed_ids: list[str] | None = None
    seed_snapshots: dict[str, TicketDraftResponse] | None = None
    direct_outcomes: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.seed_ids = []
        self.seed_snapshots = {}
        self.direct_outcomes = []

    async def close(self) -> None:
        await self.approval_runtime.close()
        await self.conversation_repository.close()
        await self.ticket_repository.close()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_data(
    intent_data: dict[str, Any],
    task_data: dict[str, Any],
) -> None:
    items = intent_data["items"]
    if len(items) != 60:
        raise ValueError(f"Expected 60 intent cases, found {len(items)}")
    counts = {label: 0 for label in INTENTS}
    for item in items:
        if item["intent"] not in counts:
            raise ValueError(f"Unknown intent label: {item['intent']}")
        counts[item["intent"]] += 1
    if any(count != 15 for count in counts.values()):
        raise ValueError(f"Intent distribution must be 15 each: {counts}")
    tasks = task_data["tasks"]
    if len(tasks) < 12:
        raise ValueError("At least 12 task definitions are required")
    if len({task["id"] for task in tasks}) != len(tasks):
        raise ValueError("Task IDs must be unique")


def estimated_model_requests(
    intent_count: int,
    tasks: list[dict[str, Any]],
) -> int:
    agent_turns = sum(len(task["turns"]) for task in tasks)
    # Agent turns normally issue Supervisor + tool model + final answer calls.
    return intent_count + agent_turns * 3


def build_llm(settings: Settings) -> DeepSeekLLM:
    if settings.deepseek_api_key is None:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    api_key = settings.deepseek_api_key.get_secret_value().strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is empty")
    return DeepSeekLLM(
        api_key=api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=float(
            os.getenv("AGENT_EVAL_TIMEOUT_SECONDS", "60")
        ),
        max_retries=int(os.getenv("AGENT_EVAL_MAX_RETRIES", "0")),
        temperature=settings.llm_temperature,
    )


async def evaluate_intents(
    llm: DeepSeekLLM,
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    nodes = AgentNodes(
        llm=llm,
        rag_service=_UnusedRagService(),  # type: ignore[arg-type]
        chat_service=object(),  # type: ignore[arg-type]
        ticket_tool_executor=_UnusedTicketTools(),  # type: ignore[arg-type]
        supervisor_prompt=SUPERVISOR_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        ticket_prompt="unused",
        max_tool_calls=1,
    )
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        started = time.perf_counter()
        error: str | None = None
        reason = ""
        observed_model = ""
        prompt_tokens = 0
        completion_tokens = 0
        try:
            state = await nodes.supervisor({"message": item["text"]})
            predicted = str(state.get("intent", "clarification"))
            reason = str(state.get("supervisor_reason", ""))
            observed_model = str(state.get("model") or "")
            error = state.get("error")
            for usage in state.get("usage_parts", []):
                prompt_tokens += usage.prompt_tokens
                completion_tokens += usage.completion_tokens
        except Exception as exc:
            predicted = "error"
            error = getattr(exc, "code", type(exc).__name__)
        latency_ms = (time.perf_counter() - started) * 1000
        rows.append(
            {
                "id": item["id"],
                "text": item["text"],
                "expected_intent": item["intent"],
                "predicted_intent": predicted,
                "correct": predicted == item["intent"],
                "reason": reason,
                "model": observed_model,
                "error": error,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        )
        if index % 10 == 0:
            print(
                f"intent-evaluation: {index}/{len(items)}",
                flush=True,
            )
    return rows


def make_agent_service(
    *,
    llm: DeepSeekLLM,
    ticket_service: TicketDraftService,
    memory: ConversationMemoryService,
) -> AgentService:
    nodes = AgentNodes(
        llm=llm,
        rag_service=_UnusedRagService(),  # type: ignore[arg-type]
        chat_service=ChatService(
            llm=llm,
            system_prompt=CHAT_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip(),
            model_name="deepseek-evaluation",
        ),
        ticket_tool_executor=TicketToolExecutor(ticket_service),
        supervisor_prompt=SUPERVISOR_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        ticket_prompt=TICKET_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        max_tool_calls=3,
    )
    workflow = AgentWorkflow(
        nodes=nodes,
        max_execution_steps=10,
    )
    return AgentService(
        workflow=workflow,
        conversation_memory=memory,
    )


async def create_task_context(
    task: dict[str, Any],
    *,
    llm: DeepSeekLLM,
    run_root: Path,
    settings: Settings,
) -> TaskContext:
    root = run_root / "tasks" / task["id"]
    root.mkdir(parents=True, exist_ok=True)
    for directory in ("qdrant", "bm25"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    ticket_repository = SQLAlchemyTicketDraftRepository(
        f"sqlite+aiosqlite:///{(root / 'tickets.db').as_posix()}"
    )
    conversation_repository = SQLAlchemyConversationRepository(
        (
            "sqlite+aiosqlite:///"
            + (root / "conversations.db").as_posix()
        )
    )
    ticket_service = TicketDraftService(ticket_repository)
    memory = ConversationMemoryService(
        repository=conversation_repository,
        ticket_service=ticket_service,
        max_history_messages=settings.agent_history_max_messages,
        history_token_budget=settings.agent_history_token_budget,
    )
    approval_runtime = await create_approval_runtime(
        checkpoint_path=root / "approval_checkpoints.db",
        repository=ticket_repository,
        max_execution_steps=settings.agent_max_execution_steps,
    )
    return TaskContext(
        task=task,
        root=root,
        ticket_repository=ticket_repository,
        conversation_repository=conversation_repository,
        ticket_service=ticket_service,
        memory=memory,
        executor=TicketToolExecutor(ticket_service),
        approval_runtime=approval_runtime,
        agent_service=make_agent_service(
            llm=llm,
            ticket_service=ticket_service,
            memory=memory,
        ),
    )


async def record_ticket_reference(
    context: TaskContext,
    draft: TicketDraftResponse,
    *,
    sequence: int,
) -> None:
    if context.conversation_id is None:
        conversation = await context.memory.begin_or_resume(None)
        context.conversation_id = conversation.id
    await context.memory.record_turn(
        conversation_id=context.conversation_id,
        user_content=f"准备评测工单 {sequence}",
        assistant_content=f"已创建工单草稿 {draft.id}。",
        intent="ticket_request",
        status="ticket_draft_ready",
        tool_results=[
            ToolResultRecord(
                tool_call_id=f"seed-{sequence}",
                name=CREATE_TICKET_DRAFT,
                status="created",
                ok=True,
                message=f"已创建工单草稿 {draft.id}。",
                draft_id=draft.id,
                error_code=None,
            )
        ],
        last_ticket_draft_id=draft.id,
    )


async def finalize_seed_status(
    context: TaskContext,
    draft: TicketDraftResponse,
    requested_status: str,
) -> TicketDraftResponse:
    if requested_status == "draft":
        return draft
    approval = await context.approval_runtime.service.request(draft.id)
    if requested_status == "pending_approval":
        return approval.draft
    if requested_status == "approved":
        result = await context.approval_runtime.service.decide(
            approval.approval.thread_id,
            ApprovalDecisionRequest(
                decision="approve",
                note="评测夹具审批",
            ),
        )
        return result.transition.draft
    raise ValueError(f"Unsupported seed status: {requested_status}")


async def seed_single_draft(
    context: TaskContext,
    setup: dict[str, Any],
) -> None:
    created = await context.ticket_service.create(
        args=CreateTicketDraftArgs(
            title=setup["title"],
            description=setup["description"],
            device_or_system=setup["device_or_system"],
        ),
        idempotency_key=f"{context.task['id']}-seed-0",
    )
    draft = await finalize_seed_status(
        context,
        created.draft,
        setup.get("status", "draft"),
    )
    context.seed_ids.append(draft.id)
    context.seed_snapshots[draft.id] = draft
    if setup.get("record_reference", False):
        await record_ticket_reference(
            context,
            draft,
            sequence=0,
        )


async def setup_task(context: TaskContext) -> None:
    setup = context.task["setup"]
    setup_type = setup["type"]
    if setup_type == "none":
        return
    if setup_type == "seed_single":
        await seed_single_draft(context, setup)
        return
    if setup_type == "seed_two":
        for index, values in enumerate(setup["drafts"]):
            created = await context.ticket_service.create(
                args=CreateTicketDraftArgs(**values),
                idempotency_key=f"{context.task['id']}-seed-{index}",
            )
            context.seed_ids.append(created.draft.id)
            context.seed_snapshots[created.draft.id] = created.draft
            if setup.get("record_references", False):
                await record_ticket_reference(
                    context,
                    created.draft,
                    sequence=index,
                )
        return
    if setup_type == "seed_cross_conversation":
        created = await context.ticket_service.create(
            args=CreateTicketDraftArgs(
                title=setup["title"],
                description=setup["description"],
                device_or_system=setup["device_or_system"],
            ),
            idempotency_key=f"{context.task['id']}-cross-seed",
        )
        context.seed_ids.append(created.draft.id)
        context.seed_snapshots[created.draft.id] = created.draft
        await record_ticket_reference(
            context,
            created.draft,
            sequence=0,
        )
        second = await context.memory.begin_or_resume(None)
        context.conversation_id = second.id
        return
    if setup_type == "direct_invalid_arguments":
        started = time.perf_counter()
        outcome = await context.executor.execute(
            LLMToolCall(
                id="eval-invalid-args",
                name=CREATE_TICKET_DRAFT,
                arguments='{"title":',
            ),
            conversation_id=None,
        )
        context.direct_outcomes.append(
            {
                "outcome": outcome.model_dump(mode="json"),
                "duration_ms": (time.perf_counter() - started) * 1000,
                "expected_rejection": True,
            }
        )
        return
    if setup_type == "direct_unknown_tool":
        started = time.perf_counter()
        outcome = await context.executor.execute(
            LLMToolCall(
                id="eval-unknown-tool",
                name="execute_python",
                arguments='{"code":"print(1)"}',
            ),
            conversation_id=None,
        )
        context.direct_outcomes.append(
            {
                "outcome": outcome.model_dump(mode="json"),
                "duration_ms": (time.perf_counter() - started) * 1000,
                "expected_rejection": True,
            }
        )
        return
    if setup_type == "direct_idempotent_create":
        conversation = await context.memory.begin_or_resume(None)
        context.conversation_id = conversation.id
        call = LLMToolCall(
            id="eval-idempotent-call",
            name=CREATE_TICKET_DRAFT,
            arguments=json.dumps(
                {
                    "title": "幂等评测工单",
                    "description": "同一工具调用只创建一份草稿。",
                    "device_or_system": "评测设备",
                },
                ensure_ascii=False,
            ),
        )
        for _ in range(2):
            started = time.perf_counter()
            outcome = await context.executor.execute(
                call,
                conversation_id=conversation.id,
            )
            context.direct_outcomes.append(
                {
                    "outcome": outcome.model_dump(mode="json"),
                    "duration_ms": (
                        time.perf_counter() - started
                    ) * 1000,
                    "expected_rejection": False,
                }
            )
        return
    raise ValueError(f"Unsupported task setup type: {setup_type}")


def current_tool_names(response: dict[str, Any]) -> list[str]:
    return [call["name"] for call in response.get("tool_calls", [])]


def tool_execution_records(
    response: dict[str, Any],
    *,
    rejection_expected: bool,
    expected_tool_options: list[list[str]],
) -> list[dict[str, Any]]:
    expected_names = {
        name for option in expected_tool_options for name in option
    }
    records: list[dict[str, Any]] = []
    for call in response.get("tool_calls", []):
        success = call["status"] in SUCCESS_TOOL_STATUSES
        expected_rejection = (
            rejection_expected
            and not success
            and call["name"] in expected_names
        )
        records.append(
            {
                "name": call["name"],
                "status": call["status"],
                "error": call.get("error"),
                "success": success,
                "expected_rejection": expected_rejection,
                "duration_ms": call.get("duration_ms", 0.0),
            }
        )
    return records


async def run_model_turns(context: TaskContext) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for turn in context.task["turns"]:
        message = turn["message"]
        if context.seed_ids:
            message = message.replace("{draft_id}", context.seed_ids[0])
        started = time.perf_counter()
        try:
            response_model = await context.agent_service.run(
                message=message,
                conversation_id=context.conversation_id,
            )
            response = response_model.model_dump(mode="json")
            context.conversation_id = response_model.conversation_id
            error = None
        except Exception as exc:
            response = {}
            error = {
                "code": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
            }
        wall_latency_ms = (time.perf_counter() - started) * 1000
        actual_tools = current_tool_names(response)
        options = turn["expected_tool_options"]
        selection_correct = actual_tools in options
        tool_records = tool_execution_records(
            response,
            rejection_expected=context.task["rejection_expected"],
            expected_tool_options=options,
        )
        turns.append(
            {
                "message": message,
                "expected_intent": turn["expected_intent"],
                "actual_intent": response.get("intent"),
                "expected_tool_options": options,
                "actual_tools": actual_tools,
                "tool_selection_correct": selection_correct,
                "response": response,
                "error": error,
                "wall_latency_ms": wall_latency_ms,
                "latency_ms": response.get("latency_ms", wall_latency_ms),
                "usage": response.get("usage"),
                "supervisor_latencies_ms": [
                    trace["duration_ms"]
                    for trace in response.get("node_traces", [])
                    if trace.get("node") == "supervisor"
                ],
                "tool_executions": tool_records,
            }
        )
        if error is not None:
            break
    return turns


def response_draft(response: dict[str, Any]) -> dict[str, Any] | None:
    return response.get("ticket_draft")


async def evaluate_assertions(
    context: TaskContext,
    turns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    current_drafts = {
        draft.id: draft for draft in await context.ticket_service.list()
    }
    results: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        results.append(
            {"assertion": name, "passed": passed, "detail": detail}
        )

    for assertion in context.task["assertions"]:
        kind = assertion["type"]
        passed = False
        detail = ""
        if kind == "draft_count_equals":
            passed = len(current_drafts) == assertion["value"]
            detail = f"draft_count={len(current_drafts)}"
        elif kind == "response_status_in":
            latest = turns[-1]["response"] if turns else {}
            status = latest.get("status")
            passed = status in assertion["values"]
            detail = f"status={status}"
        elif kind == "response_draft_field_contains":
            latest = turns[-1]["response"] if turns else {}
            draft = response_draft(latest) or {}
            field_value = str(draft.get(assertion["field"], "")).lower()
            passed = any(
                value.lower() in field_value
                for value in assertion["values"]
            )
            detail = f"{assertion['field']}={field_value}"
        elif kind == "response_draft_description_contains":
            latest = turns[-1]["response"] if turns else {}
            description = (
                response_draft(latest) or {}
            ).get("description", "").lower()
            passed = any(
                value.lower() in description
                for value in assertion["values"]
            )
            detail = f"description={description}"
        elif kind == "response_draft_id_equals_seed":
            latest = turns[-1]["response"] if turns else {}
            draft_id = (response_draft(latest) or {}).get("id")
            expected = context.seed_ids[assertion["index"]]
            passed = draft_id == expected
            detail = f"response_draft_id={draft_id} seed={expected}"
        elif kind == "seed_draft_unchanged":
            seed_id = context.seed_ids[assertion["index"]]
            expected = context.seed_snapshots[seed_id]
            actual = current_drafts.get(seed_id)
            passed = actual is not None and (
                actual.title,
                actual.description,
                actual.device_or_system,
                actual.status,
                actual.version,
            ) == (
                expected.title,
                expected.description,
                expected.device_or_system,
                expected.status,
                expected.version,
            )
            detail = (
                f"actual={actual.model_dump(mode='json') if actual else None}"
            )
        elif kind == "all_seed_drafts_unchanged":
            unchanged = True
            for seed_id in context.seed_ids:
                expected = context.seed_snapshots[seed_id]
                actual = current_drafts.get(seed_id)
                if actual is None or (
                    actual.title,
                    actual.description,
                    actual.device_or_system,
                    actual.status,
                    actual.version,
                ) != (
                    expected.title,
                    expected.description,
                    expected.device_or_system,
                    expected.status,
                    expected.version,
                ):
                    unchanged = False
                    break
            passed = unchanged
            detail = f"seed_ids={context.seed_ids}"
        elif kind == "seed_draft_version_at_least":
            seed_id = context.seed_ids[assertion["index"]]
            actual = current_drafts.get(seed_id)
            passed = actual is not None and actual.version >= assertion["value"]
            detail = f"version={actual.version if actual else None}"
        elif kind == "seed_draft_status_equals":
            seed_id = context.seed_ids[assertion["index"]]
            actual = current_drafts.get(seed_id)
            passed = actual is not None and actual.status == assertion["value"]
            detail = f"status={actual.status if actual else None}"
        elif kind == "turn_draft_ids_equal":
            first = response_draft(turns[assertion["first"]]["response"]) or {}
            second = response_draft(
                turns[assertion["second"]]["response"]
            ) or {}
            passed = bool(first.get("id")) and first.get("id") == second.get("id")
            detail = f"first={first.get('id')} second={second.get('id')}"
        elif kind == "last_response_description_contains":
            latest = turns[-1]["response"] if turns else {}
            description = (
                response_draft(latest) or {}
            ).get("description", "").lower()
            passed = any(
                value.lower() in description
                for value in assertion["values"]
            )
            detail = f"description={description}"
        elif kind == "conversation_message_count_at_least":
            if context.conversation_id is None:
                passed = False
                detail = "conversation_id is None"
            else:
                history = await context.memory.get_history(
                    context.conversation_id,
                    limit=200,
                )
                passed = history.total >= assertion["value"]
                detail = f"message_count={history.total}"
        elif kind == "refusal_match":
            errors = {
                (turn.get("error") or {}).get("code")
                for turn in turns
                if turn.get("error")
            }
            errors.update(
                call.get("error")
                for turn in turns
                for call in turn.get("tool_executions", [])
                if call.get("error")
            )
            answers = " ".join(
                turn["response"].get("answer") or ""
                for turn in turns
            )
            matched_error = bool(errors & set(assertion["errors"]))
            matched_answer = any(
                keyword in answers
                for keyword in assertion["answer_keywords"]
            )
            latest = turns[-1] if turns else {}
            actual_tools = latest.get("actual_tools", [])
            safe_clarification = (
                assertion.get("allow_safe_clarification", False)
                and latest.get("actual_intent") == "clarification"
                and not actual_tools
            )
            passed = matched_error or matched_answer or safe_clarification
            detail = (
                f"errors={sorted(str(item) for item in errors if item)}; "
                f"safe_clarification={safe_clarification}"
            )
        elif kind == "conversation_reference_count_equals":
            if context.conversation_id is None:
                count = 0
            else:
                count = len(
                    await context.memory.get_ticket_references(
                        context.conversation_id
                    )
                )
            passed = count == assertion["value"]
            detail = f"reference_count={count}"
        elif kind == "direct_error_code":
            outcome = (
                ToolExecutionOutcome.model_validate(
                    context.direct_outcomes[assertion["index"]]["outcome"]
                )
            )
            passed = outcome.error_code == assertion["value"]
            detail = f"error_code={outcome.error_code}"
        elif kind == "direct_idempotent_same_draft":
            outcomes = [
                ToolExecutionOutcome.model_validate(item["outcome"])
                for item in context.direct_outcomes
            ]
            passed = (
                len(outcomes) == 2
                and outcomes[0].created is True
                and outcomes[1].created is False
                and outcomes[0].draft is not None
                and outcomes[1].draft is not None
                and outcomes[0].draft.id == outcomes[1].draft.id
            )
            detail = (
                f"created={[item.created for item in outcomes]}"
            )
        else:
            detail = f"Unsupported assertion type: {kind}"
        add(kind, passed, detail)

    all_passed = all(item["passed"] for item in results)
    return results, all_passed


async def run_task(
    task: dict[str, Any],
    *,
    llm: DeepSeekLLM,
    run_root: Path,
    settings: Settings,
) -> dict[str, Any]:
    started = time.perf_counter()
    context = await create_task_context(
        task,
        llm=llm,
        run_root=run_root,
        settings=settings,
    )
    try:
        await setup_task(context)
        turns = await run_model_turns(context) if task["turns"] else []
        assertions, assertions_passed = await evaluate_assertions(
            context,
            turns,
        )
        failed_turns = [turn for turn in turns if turn.get("error")]
        success = (
            assertions_passed
            and not failed_turns
            and len(turns) == len(task["turns"])
        )
        tool_executions = [
            execution
            for turn in turns
            for execution in turn["tool_executions"]
        ]
        for direct in context.direct_outcomes or []:
            outcome = ToolExecutionOutcome.model_validate(direct["outcome"])
            tool_executions.append(
                {
                    "name": "direct_tool",
                    "status": outcome.status,
                    "error": outcome.error_code,
                    "success": outcome.ok,
                    "expected_rejection": direct["expected_rejection"],
                    "duration_ms": direct["duration_ms"],
                }
            )
        failure_reasons = [
            f"{item['assertion']}: {item['detail']}"
            for item in assertions
            if not item["passed"]
        ]
        failure_reasons.extend(
            f"turn error: {(turn.get('error') or {}).get('code')}"
            for turn in failed_turns
        )
        answers = " ".join(
            turn["response"].get("answer") or "" for turn in turns
        )
        claimed_success = any(
            marker in answers
            for marker in ("已保存", "已创建", "已更新")
        )
        db_assertion_failures = [
            item for item in assertions
            if not item["passed"]
            and item["assertion"] in {
                "draft_count_equals",
                "seed_draft_unchanged",
                "all_seed_drafts_unchanged",
                "seed_draft_version_at_least",
                "seed_draft_status_equals",
            }
        ]
        return {
            "task_id": task["id"],
            "name": task["name"],
            "category": task["category"],
            "success": success,
            "failure_reasons": failure_reasons,
            "assertions": assertions,
            "turns": turns,
            "tool_selection": [
                {
                    "message": turn["message"],
                    "expected_tool_options": turn[
                        "expected_tool_options"
                    ],
                    "actual_tools": turn["actual_tools"],
                    "correct": turn["tool_selection_correct"],
                }
                for turn in turns
            ],
            "tool_executions": tool_executions,
            "direct_outcomes": context.direct_outcomes or [],
            "seed_draft_ids": context.seed_ids or [],
            "total_latency_ms": (
                time.perf_counter() - started
            ) * 1000,
            "claimed_success_db_mismatch": (
                claimed_success and bool(db_assertion_failures)
            ),
            "isolated_paths": {
                "tickets": str(context.root / "tickets.db"),
                "conversations": str(context.root / "conversations.db"),
                "checkpoints": str(
                    context.root / "approval_checkpoints.db"
                ),
                "qdrant": str(context.root / "qdrant"),
                "bm25": str(context.root / "bm25"),
            },
        }
    finally:
        await context.close()


def prompt_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    intent_data = load_json(INTENTS_PATH)
    task_data = load_json(TASKS_PATH)
    validate_data(intent_data, task_data)
    if args.validate_only:
        print("agent-evaluation-data: valid")
        print(
            "estimated-model-requests:",
            estimated_model_requests(
                len(intent_data["items"]),
                task_data["tasks"],
            ),
        )
        return 0
    if os.getenv("RUN_REAL_AGENT_EVALS") != "1" or not args.real:
        print(
            "Real evaluation is disabled. Set RUN_REAL_AGENT_EVALS=1 "
            "and pass --real to consume DeepSeek API quota."
        )
        return 2

    max_requests = int(os.getenv("AGENT_EVAL_MAX_REQUESTS", "120"))
    estimated = estimated_model_requests(
        len(intent_data["items"]),
        task_data["tasks"],
    )
    if estimated > max_requests:
        raise RuntimeError(
            f"Estimated model requests {estimated} exceed limit {max_requests}"
        )

    settings = Settings()
    llm = build_llm(settings)
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    run_root = PROJECT_ROOT / "storage" / "e2e" / "agent_eval_v1" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        intent_rows = await evaluate_intents(
            llm,
            intent_data["items"],
        )
        task_results: list[dict[str, Any]] = []
        for index, task in enumerate(task_data["tasks"], start=1):
            result = await run_task(
                task,
                llm=llm,
                run_root=run_root,
                settings=settings,
            )
            task_results.append(result)
            print(
                f"task-evaluation: {index}/{len(task_data['tasks'])} "
                f"{task['id']} success={result['success']}",
                flush=True,
            )
    finally:
        await llm.aclose()

    result = {
        "metadata": {
            "run_id": run_id,
            "run_date": datetime.now(timezone.utc).isoformat(),
            "model": settings.deepseek_model,
            "observed_models": sorted(
                {
                    row["model"]
                    for row in intent_rows
                    if row.get("model")
                }
                | {
                    turn["response"].get("model")
                    for task in task_results
                    for turn in task["turns"]
                    if turn["response"].get("model")
                }
            ),
            "base_url": settings.deepseek_base_url,
            "temperature": settings.llm_temperature,
            "max_retries": int(
                os.getenv("AGENT_EVAL_MAX_RETRIES", "0")
            ),
            "estimated_model_requests": estimated,
            "max_model_requests": max_requests,
            "intent_data_version": intent_data["version"],
            "task_data_version": task_data["version"],
            "supervisor_prompt_sha256_16": prompt_hash(
                SUPERVISOR_PROMPT_PATH
            ),
            "ticket_prompt_sha256_16": prompt_hash(
                TICKET_PROMPT_PATH
            ),
            "runtime_root": str(run_root),
            "label_policy": (
                "Human labels are fixed before model execution and are "
                "never rewritten from predictions."
            ),
        },
        "intent_evaluation": intent_metrics(intent_rows),
        "intent_rows": intent_rows,
        "task_evaluation": task_metrics(task_results),
        "task_category_counts": task_category_counts(task_results),
        "task_results": task_results,
    }
    json_path = RESULTS_DIR / f"{run_id}.json"
    markdown_path = RESULTS_DIR / f"{run_id}.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        markdown_report(result),
        encoding="utf-8",
    )
    print(f"results-json: {json_path}")
    print(f"results-markdown: {markdown_path}")
    print(
        "intent-accuracy:",
        f"{result['intent_evaluation']['accuracy']:.4f}",
    )
    print(
        "task-success-rate:",
        f"{result['task_evaluation']['task_success_rate']:.4f}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
