"""Persistent multi-turn Agent conversation memory tests."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.agents.nodes import AgentNodes
from app.agents.service import AgentService
from app.agents.workflow import AgentWorkflow
from app.api.deps import (
    get_agent_service,
    get_conversation_memory_service,
)
from app.conversations.exceptions import ConversationPersistenceError
from app.conversations.repository import SQLAlchemyConversationRepository
from app.conversations.service import (
    ConversationMemoryService,
    estimate_tokens,
    trim_history,
)
from app.conversations.types import (
    ConversationMessageRecord,
    ToolResultRecord,
)
from app.core.exceptions import LLMTimeoutError
from app.llm.base import LLMToolCall, LLMToolResponse
from app.main import app
from app.schemas.ticket import CreateTicketDraftArgs
from app.tickets.repository import SQLAlchemyTicketDraftRepository
from app.tickets.service import TicketDraftService
from app.tools.ticket_tools import (
    CREATE_TICKET_DRAFT,
    UPDATE_TICKET_DRAFT,
    TicketToolExecutor,
)
from tests.fakes import FakeLLM
from tests.test_agent import (
    StaticChatService,
    StaticRagService,
    supervisor_result,
)


@dataclass(slots=True)
class MemoryHarness:
    ticket_repository: SQLAlchemyTicketDraftRepository
    conversation_repository: SQLAlchemyConversationRepository
    ticket_service: TicketDraftService
    tool_executor: TicketToolExecutor
    memory: ConversationMemoryService

    async def close(self) -> None:
        await self.conversation_repository.close()
        await self.ticket_repository.close()


async def make_harness(tmp_path: Path) -> MemoryHarness:
    ticket_repository = SQLAlchemyTicketDraftRepository(
        f"sqlite+aiosqlite:///{(tmp_path / 'tickets.db').as_posix()}"
    )
    conversation_repository = SQLAlchemyConversationRepository(
        (
            "sqlite+aiosqlite:///"
            + (tmp_path / "conversations.db").as_posix()
        )
    )
    ticket_service = TicketDraftService(ticket_repository)
    return MemoryHarness(
        ticket_repository=ticket_repository,
        conversation_repository=conversation_repository,
        ticket_service=ticket_service,
        tool_executor=TicketToolExecutor(ticket_service),
        memory=ConversationMemoryService(
            repository=conversation_repository,
            ticket_service=ticket_service,
            max_history_messages=12,
            history_token_budget=1_000,
        ),
    )


def make_agent(
    harness: MemoryHarness,
    llm: FakeLLM,
    *,
    rag: StaticRagService | None = None,
    chat: StaticChatService | None = None,
) -> AgentService:
    nodes = AgentNodes(
        llm=llm,
        rag_service=rag or StaticRagService(),
        chat_service=chat or StaticChatService(),
        ticket_tool_executor=harness.tool_executor,
        supervisor_prompt="根据历史和当前请求判断意图。",
        ticket_prompt="只能通过工具处理真实工单草稿。",
        max_tool_calls=3,
    )
    return AgentService(
        workflow=AgentWorkflow(
            nodes=nodes,
            max_execution_steps=10,
        ),
        conversation_memory=harness.memory,
    )


def tool_response(
    *,
    call_id: str,
    name: str,
    arguments: dict,
) -> LLMToolResponse:
    return LLMToolResponse(
        content=None,
        model="fake-tool-model",
        tool_calls=(
            LLMToolCall(
                id=call_id,
                name=name,
                arguments=json.dumps(arguments, ensure_ascii=False),
            ),
        ),
        prompt_tokens=20,
        completion_tokens=10,
    )


def final_response(content: str = "已完成。") -> LLMToolResponse:
    return LLMToolResponse(
        content=content,
        model="fake-tool-model",
        prompt_tokens=10,
        completion_tokens=5,
    )


async def test_two_turn_ticket_update_and_persistent_history(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    llm = FakeLLM(
        results=[
            supervisor_result("ticket_request"),
            supervisor_result("ticket_request"),
        ],
        tool_results=[
            tool_response(
                call_id="call-create-memory",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "电脑无法联网",
                    "description": "办公电脑无法连接公司网络。",
                    "device_or_system": "Windows 笔记本",
                },
            ),
            final_response("工单草稿已保存。"),
        ],
    )
    service = make_agent(harness, llm)
    try:
        first = await service.run(
            message="帮我创建一个电脑无法联网的工单。",
            conversation_id=None,
        )
        assert first.memory_persisted is True
        assert first.conversation_id is not None
        assert first.ticket_draft is not None
        draft_id = first.ticket_draft.id

        llm._tool_index = 0
        llm.tool_results = [
            tool_response(
                call_id="call-update-memory",
                name=UPDATE_TICKET_DRAFT,
                arguments={
                    "draft_id": draft_id,
                    "description": "无法连接 Wi-Fi。",
                },
            ),
            final_response("工单问题描述已更新。"),
        ]
        second = await service.run(
            message="把刚才那个工单的问题描述改成无法连接 Wi-Fi。",
            conversation_id=first.conversation_id,
        )

        assert second.ticket_draft is not None
        assert second.ticket_draft.id == draft_id
        assert second.ticket_draft.description == "无法连接 Wi-Fi。"
        stored = await harness.ticket_service.get(draft_id)
        assert stored.description == "无法连接 Wi-Fi。"
        assert stored.version == 2

        history = await harness.memory.get_history(
            first.conversation_id,
            limit=50,
        )
        assert history.total == 6
        assert [message.role for message in history.messages] == [
            "user",
            "tool",
            "assistant",
            "user",
            "tool",
            "assistant",
        ]
        assert history.messages[1].business_reference_id == draft_id
        assert history.messages[4].business_reference_id == draft_id
        assert history.conversation.last_ticket_draft_id == draft_id
        assert any(
            draft_id in message["content"]
            for message in llm.last_tool_messages
            if message["role"] == "system"
        )
    finally:
        await harness.close()


async def test_conversation_survives_repository_restart(
    tmp_path: Path,
) -> None:
    first_harness = await make_harness(tmp_path)
    first_llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-restart-create",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "打印机无法打印",
                    "description": "财务打印机没有输出。",
                    "device_or_system": "财务打印机",
                },
            ),
            final_response("草稿已保存。"),
        ],
    )
    first_service = make_agent(first_harness, first_llm)
    first = await first_service.run(
        message="创建打印机故障工单。",
        conversation_id=None,
    )
    assert first.ticket_draft is not None and first.conversation_id is not None
    conversation_id = first.conversation_id
    draft_id = first.ticket_draft.id
    await first_harness.close()

    second_harness = await make_harness(tmp_path)
    second_llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-restart-update",
                name=UPDATE_TICKET_DRAFT,
                arguments={
                    "draft_id": draft_id,
                    "description": "无法连接 Wi-Fi。",
                },
            ),
            final_response("草稿已更新。"),
        ],
    )
    second_service = make_agent(second_harness, second_llm)
    try:
        second = await second_service.run(
            message="把刚才那个工单改成无法连接 Wi-Fi。",
            conversation_id=conversation_id,
        )
        assert second.conversation_id == conversation_id
        assert second.ticket_draft is not None
        assert second.ticket_draft.description == "无法连接 Wi-Fi。"
        history = await second_harness.memory.get_history(
            conversation_id,
            limit=20,
        )
        assert history.total == 6
    finally:
        await second_harness.close()


async def test_cross_conversation_ticket_reference_is_blocked(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    first_llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-private-create",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "会话一私有草稿",
                    "description": "只属于会话一。",
                    "device_or_system": "测试设备",
                },
            ),
            final_response("已创建。"),
        ],
    )
    first_service = make_agent(harness, first_llm)
    try:
        first = await first_service.run(
            message="创建会话一工单。",
            conversation_id=None,
        )
        assert first.ticket_draft is not None
        draft_id = first.ticket_draft.id

        second_llm = FakeLLM(
            result=supervisor_result("ticket_request"),
            tool_results=[
                tool_response(
                    call_id="call-cross-update",
                    name=UPDATE_TICKET_DRAFT,
                    arguments={
                        "draft_id": draft_id,
                        "description": "跨会话篡改",
                    },
                ),
                final_response("不应成功。"),
            ],
        )
        second_service = make_agent(harness, second_llm)
        second = await second_service.run(
            message=f"修改工单 {draft_id}。",
            conversation_id=None,
        )

        assert second.error == "TICKET_REFERENCE_NOT_ALLOWED"
        assert second.ticket_draft is None
        assert second.conversation_id != first.conversation_id
        stored = await harness.ticket_service.get(draft_id)
        assert stored.description == "只属于会话一。"
        assert await harness.memory.get_ticket_references(
            second.conversation_id
        ) == []
    finally:
        await harness.close()


async def test_multiple_editable_targets_require_explicit_clarification(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    conversation = await harness.memory.begin_or_resume(None)
    first = await harness.ticket_service.create(
        args=CreateTicketDraftArgs(
            title="草稿一",
            description="第一个问题。",
            device_or_system="设备一",
        ),
        idempotency_key="multi-one",
    )
    second = await harness.ticket_service.create(
        args=CreateTicketDraftArgs(
            title="草稿二",
            description="第二个问题。",
            device_or_system="设备二",
        ),
        idempotency_key="multi-two",
    )
    for index, draft in enumerate((first.draft, second.draft), start=1):
        await harness.memory.record_turn(
            conversation_id=conversation.id,
            user_content=f"创建草稿 {index}",
            assistant_content=f"已创建 {draft.id}",
            intent="ticket_request",
            status="ticket_draft_ready",
            tool_results=[
                ToolResultRecord(
                    tool_call_id=f"seed-{index}",
                    name=CREATE_TICKET_DRAFT,
                    status="created",
                    ok=True,
                    message=f"已创建 {draft.id}",
                    draft_id=draft.id,
                    error_code=None,
                )
            ],
            last_ticket_draft_id=draft.id,
        )

    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-ambiguous-update",
                name=UPDATE_TICKET_DRAFT,
                arguments={
                    "draft_id": second.draft.id,
                    "description": "猜测修改",
                },
            ),
            final_response("需要明确目标。"),
        ],
    )
    service = make_agent(harness, llm)
    try:
        response = await service.run(
            message="把刚才那个工单的问题描述改一下。",
            conversation_id=conversation.id,
        )
        assert response.status == "needs_clarification"
        assert response.error == "TICKET_TARGET_AMBIGUOUS"
        assert "明确" in (response.answer or "")
        unchanged = await harness.ticket_service.get(second.draft.id)
        assert unchanged.description == "第二个问题。"
    finally:
        await harness.close()


async def test_pending_approval_cannot_be_updated_through_memory_turn(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    conversation = await harness.memory.begin_or_resume(None)
    created = await harness.ticket_service.create(
        args=CreateTicketDraftArgs(
            title="审批中的草稿",
            description="原始描述。",
            device_or_system="测试设备",
        ),
        idempotency_key="pending-memory",
    )
    await harness.memory.record_turn(
        conversation_id=conversation.id,
        user_content="创建审批草稿",
        assistant_content=f"已创建 {created.draft.id}",
        intent="ticket_request",
        status="ticket_draft_ready",
        tool_results=[
            ToolResultRecord(
                tool_call_id="seed-pending",
                name=CREATE_TICKET_DRAFT,
                status="created",
                ok=True,
                message=f"已创建 {created.draft.id}",
                draft_id=created.draft.id,
                error_code=None,
            )
        ],
        last_ticket_draft_id=created.draft.id,
    )
    with sqlite3.connect(tmp_path / "tickets.db") as connection:
        connection.execute(
            "UPDATE ticket_drafts SET status = 'pending_approval' "
            "WHERE id = ?",
            (created.draft.id,),
        )
        connection.commit()

    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-pending-update",
                name=UPDATE_TICKET_DRAFT,
                arguments={
                    "draft_id": created.draft.id,
                    "description": "试图绕过审批",
                },
            ),
            final_response("更新失败。"),
        ],
    )
    service = make_agent(harness, llm)
    try:
        response = await service.run(
            message="修改刚才那个工单。",
            conversation_id=conversation.id,
        )
        assert response.error == "TICKET_DRAFT_STATE_CONFLICT"
        stored = await harness.ticket_service.get(created.draft.id)
        assert stored.description == "原始描述。"
        assert stored.status == "pending_approval"
    finally:
        await harness.close()


async def test_knowledge_turns_use_history_but_current_rag_evidence(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    llm = FakeLLM(
        results=[
            supervisor_result("knowledge_query"),
            supervisor_result("knowledge_query"),
        ]
    )
    rag = StaticRagService()
    service = make_agent(harness, llm, rag=rag)
    try:
        first = await service.run(
            message="Redis 缓存击穿怎么处理？",
            conversation_id=None,
        )
        second = await service.run(
            message="再总结一下这些方法。",
            conversation_id=first.conversation_id,
        )

        assert [call["query"] for call in rag.calls] == [
            "Redis 缓存击穿怎么处理？",
            "再总结一下这些方法。",
        ]
        assert second.sources[0].filename == "redis.txt"
        assert "<untrusted_conversation_history>" in llm.last_user_message
        history = await harness.memory.get_history(
            first.conversation_id,
            limit=20,
        )
        assert history.total == 4
        assert all(
            message.intent == "knowledge_query"
            for message in history.messages
        )
    finally:
        await harness.close()


async def test_general_chat_receives_bounded_conversation_history(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    llm = FakeLLM(
        results=[
            supervisor_result("general_chat"),
            supervisor_result("general_chat"),
        ]
    )
    chat = StaticChatService(answer="你好。")
    service = make_agent(harness, llm, chat=chat)
    try:
        first = await service.run(
            message="你好。",
            conversation_id=None,
        )
        await service.run(
            message="继续介绍一下你自己。",
            conversation_id=first.conversation_id,
        )

        assert chat.history_contexts[0] == ""
        assert "你好。" in chat.history_contexts[1]
        assert "<untrusted_conversation_history>" in (
            chat.history_contexts[1]
        )
        assert "<untrusted_conversation_history>" in llm.last_user_message
    finally:
        await harness.close()


def test_history_is_trimmed_by_message_count_and_token_budget() -> None:
    messages = [
        ConversationMessageRecord(
            id=index,
            conversation_id="a" * 32,
            role="user" if index % 2 else "assistant",
            content=(
                f"第 {index} 条消息 " + "很长的上下文 " * 12
            ),
            intent="general_chat",
            status="completed",
            tool_name=None,
            tool_status=None,
            business_reference_id=None,
            created_at=datetime.now(timezone.utc),
        )
        for index in range(20)
    ]

    trimmed = trim_history(
        messages,
        max_messages=4,
        token_budget=90,
    )

    assert 0 < len(trimmed) <= 4
    assert trimmed[-1].id == 19
    assert sum(
        estimate_tokens(message.content) + 4
        for message in trimmed
    ) <= 90
    assert [message.id for message in trimmed] == sorted(
        message.id for message in trimmed
    )


async def test_model_failure_records_no_tool_success(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    service = make_agent(
        harness,
        FakeLLM(error=LLMTimeoutError()),
    )
    try:
        conversation = await harness.memory.begin_or_resume(None)
        with pytest.raises(LLMTimeoutError):
            await service.run(
                message="创建一个不能成功的工单。",
                conversation_id=conversation.id,
            )
        history = await harness.conversation_repository.list_messages(
            conversation.id,
            limit=10,
        )
        assert [message.role for message in history] == [
            "user",
            "assistant",
        ]
        assert history[0].content == "创建一个不能成功的工单。"
        assert history[1].status == "service_error"
        assert all(message.role != "tool" for message in history)
    finally:
        await harness.close()


async def test_unknown_conversation_is_not_created(tmp_path: Path) -> None:
    harness = await make_harness(tmp_path)
    try:
        with pytest.raises(Exception) as caught:
            await harness.memory.begin_or_resume("f" * 32)
        assert getattr(caught.value, "code", "") == "CONVERSATION_NOT_FOUND"
    finally:
        await harness.close()


async def test_conversation_write_failure_is_not_reported_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await make_harness(tmp_path)
    service = make_agent(
        harness,
        FakeLLM(result=supervisor_result("general_chat")),
    )

    async def fail_write(**kwargs):
        raise ConversationPersistenceError()

    monkeypatch.setattr(harness.memory, "record_turn", fail_write)
    try:
        with pytest.raises(ConversationPersistenceError):
            await service.run(
                message="你好",
                conversation_id=None,
            )
    finally:
        await harness.close()


async def test_tool_idempotency_is_scoped_per_conversation(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    call = LLMToolCall(
        id="same-model-call-id",
        name=CREATE_TICKET_DRAFT,
        arguments=json.dumps(
            {
                "title": "会话隔离测试",
                "description": "相同 call id 不应跨会话复用。",
                "device_or_system": "测试设备",
            },
            ensure_ascii=False,
        ),
    )
    try:
        first = await harness.tool_executor.execute(
            call,
            conversation_id="a" * 32,
        )
        replay = await harness.tool_executor.execute(
            call,
            conversation_id="a" * 32,
        )
        other = await harness.tool_executor.execute(
            call,
            conversation_id="b" * 32,
        )
        assert first.draft is not None and replay.draft is not None
        assert other.draft is not None
        assert first.draft.id == replay.draft.id
        assert other.draft.id != first.draft.id
        assert replay.created is False
        assert other.created is True
    finally:
        await harness.close()


async def test_conversation_api_returns_persisted_history(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    llm = FakeLLM(result=supervisor_result("general_chat"))
    service = make_agent(harness, llm)
    app.dependency_overrides[get_agent_service] = lambda: service
    app.dependency_overrides[get_conversation_memory_service] = (
        lambda: harness.memory
    )
    try:
        run_response = await client.post(
            "/api/v1/agent/run",
            json={"message": "你好"},
        )
        assert run_response.status_code == 200
        run_body = run_response.json()
        assert run_body["memory_persisted"] is True
        conversation_id = run_body["conversation_id"]
        assert conversation_id

        history_response = await client.get(
            f"/api/v1/agent/conversations/{conversation_id}"
        )
        assert history_response.status_code == 200
        history = history_response.json()
        assert history["total"] == 2
        assert [item["role"] for item in history["messages"]] == [
            "user",
            "assistant",
        ]

        missing = await client.get(
            f"/api/v1/agent/conversations/{'f' * 32}"
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    finally:
        await harness.close()
