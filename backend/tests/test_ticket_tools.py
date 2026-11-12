"""Native tool calling, ticket draft validation, and SQLite persistence tests."""

import json
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_agent_service, get_ticket_service
from app.llm.base import LLMToolCall, LLMToolResponse
from app.main import app
from app.schemas.ticket import CreateTicketDraftArgs, TicketDraftUpdateRequest
from app.tickets.exceptions import TicketPersistenceError
from app.tickets.repository import SQLAlchemyTicketDraftRepository
from app.tickets.service import TicketDraftService
from app.tools.ticket_tools import (
    CREATE_TICKET_DRAFT,
    GET_TICKET_DRAFT,
    UPDATE_TICKET_DRAFT,
    TicketToolExecutor,
)
from tests.fakes import FakeLLM
from tests.test_agent import make_service, supervisor_result


def make_ticket_dependencies(
    database_path: Path,
) -> tuple[
    SQLAlchemyTicketDraftRepository,
    TicketDraftService,
    TicketToolExecutor,
]:
    repository = SQLAlchemyTicketDraftRepository(
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    service = TicketDraftService(repository)
    return repository, service, TicketToolExecutor(service)


def tool_call(
    *,
    call_id: str,
    name: str,
    arguments: dict,
) -> LLMToolCall:
    return LLMToolCall(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
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
            tool_call(
                call_id=call_id,
                name=name,
                arguments=arguments,
            ),
        ),
        prompt_tokens=40,
        completion_tokens=15,
    )


def final_tool_response() -> LLMToolResponse:
    return LLMToolResponse(
        content="工具调用已经完成。",
        model="fake-tool-model",
        prompt_tokens=25,
        completion_tokens=8,
    )


async def test_create_get_update_and_restart_persistence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tickets.db"
    repository, service, _ = make_ticket_dependencies(path)
    try:
        created = await service.create(
            args=CreateTicketDraftArgs(
                title="电脑无法联网",
                description="办公电脑无法连接公司网络。",
                device_or_system="Windows 笔记本",
            ),
            idempotency_key="stable-call-id",
        )
        replay = await service.create(
            args=CreateTicketDraftArgs(
                title="电脑无法联网",
                description="办公电脑无法连接公司网络。",
                device_or_system="Windows 笔记本",
            ),
            idempotency_key="stable-call-id",
        )

        assert created.created is True
        assert replay.created is False
        assert replay.draft.id == created.draft.id
        assert created.draft.status == "draft"

        updated = await service.update(
            created.draft.id,
            TicketDraftUpdateRequest(
                description="电脑无法联网，已确认网线正常。"
            ),
        )
        assert "网线正常" in updated.description
        assert updated.updated_at >= updated.created_at
    finally:
        await repository.close()

    restarted_repository, restarted_service, _ = make_ticket_dependencies(path)
    try:
        restored = await restarted_service.get(created.draft.id)
        listed = await restarted_service.list()
        assert restored.description == "电脑无法联网，已确认网线正常。"
        assert [draft.id for draft in listed] == [created.draft.id]
    finally:
        await restarted_repository.close()


async def test_executor_handles_idempotency_and_invalid_inputs(
    tmp_path: Path,
) -> None:
    repository, _, executor = make_ticket_dependencies(tmp_path / "tickets.db")
    try:
        call = tool_call(
            call_id="call-create-1",
            name=CREATE_TICKET_DRAFT,
            arguments={
                "title": "打印机无法打印",
                "description": "打印机连接后无法输出文档。",
                "device_or_system": "财务打印机",
            },
        )
        first = await executor.execute(call, conversation_id="conversation-1")
        second = await executor.execute(call, conversation_id="conversation-1")
        unknown = await executor.execute(
            tool_call(
                call_id="call-unknown",
                name="execute_python",
                arguments={"code": "print(1)"},
            ),
            conversation_id="conversation-1",
        )
        missing = await executor.execute(
            tool_call(
                call_id="call-missing",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "",
                    "description": "",
                    "device_or_system": "",
                },
            ),
            conversation_id="conversation-1",
        )
        invalid_json = await executor.execute(
            LLMToolCall(
                id="call-invalid-json",
                name=CREATE_TICKET_DRAFT,
                arguments="not-json",
            ),
            conversation_id="conversation-1",
        )

        assert first.ok is True and first.created is True
        assert second.ok is True and second.created is False
        assert second.draft and first.draft
        assert second.draft.id == first.draft.id
        assert unknown.error_code == "UNKNOWN_TOOL"
        assert missing.status == "needs_more_info"
        assert missing.missing_fields == [
            "title",
            "description",
            "device_or_system",
        ]
        assert invalid_json.error_code == "INVALID_TOOL_ARGUMENTS"
    finally:
        await repository.close()


async def test_ticket_agent_executes_native_tool_loop_and_persists(
    tmp_path: Path,
) -> None:
    repository, ticket_service, executor = make_ticket_dependencies(
        tmp_path / "tickets.db"
    )
    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-create-2",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "电脑无法联网",
                    "description": "用户电脑无法连接网络。",
                    "device_or_system": "办公电脑",
                },
            ),
            final_tool_response(),
        ],
    )
    service = make_service(llm, tool_executor=executor)
    try:
        response = await service.run(
            message="帮我创建电脑无法联网的工单草稿。",
            conversation_id="conversation-2",
        )

        assert response.intent == "ticket_request"
        assert response.status == "ticket_draft_ready"
        assert response.ticket_draft is not None
        assert response.executed_nodes == [
            "supervisor",
            "ticket_agent",
            "ticket_tools",
            "ticket_agent",
        ]
        assert response.ticket_draft.title == "电脑无法联网"
        persisted = await ticket_service.get(response.ticket_draft.id)
        assert persisted.description == "用户电脑无法连接网络。"
        assert any(
            item.node == "tool:create_ticket_draft"
            for item in response.node_traces
        )
    finally:
        await repository.close()


async def test_get_and_update_through_native_tool_calls(
    tmp_path: Path,
) -> None:
    repository, ticket_service, executor = make_ticket_dependencies(
        tmp_path / "tickets.db"
    )
    draft = await ticket_service.create(
        args=CreateTicketDraftArgs(
            title="电脑无法联网",
            description="原问题描述。",
            device_or_system="办公电脑",
        ),
        idempotency_key="seed-draft",
    )
    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-get",
                name=GET_TICKET_DRAFT,
                arguments={"draft_id": draft.draft.id},
            ),
            tool_response(
                call_id="call-update",
                name=UPDATE_TICKET_DRAFT,
                arguments={
                    "draft_id": draft.draft.id,
                    "description": "更新后：网卡驱动需要重装。",
                },
            ),
            final_tool_response(),
        ],
    )
    service = make_service(llm, tool_executor=executor)
    try:
        response = await service.run(
            message=f"查询并修改草稿 {draft.draft.id} 的描述。",
            conversation_id="conversation-3",
        )

        assert response.status == "ticket_draft_ready"
        assert response.ticket_draft is not None
        assert "网卡驱动" in response.ticket_draft.description
        stored = await ticket_service.get(draft.draft.id)
        assert "网卡驱动" in stored.description
        tool_traces = [
            item for item in response.node_traces
            if item.node.startswith("tool:")
        ]
        assert [item.node for item in tool_traces] == [
            "tool:get_ticket_draft",
            "tool:update_ticket_draft",
        ]
    finally:
        await repository.close()


async def test_database_failure_is_not_reported_as_success(
    tmp_path: Path,
) -> None:
    class FailingRepository:
        async def create(self, **kwargs):
            raise TicketPersistenceError()

        async def get(self, draft_id):
            return None

        async def update(self, draft_id, values):
            return None

        async def list(self):
            return []

        async def close(self):
            return None

    ticket_service = TicketDraftService(FailingRepository())
    executor = TicketToolExecutor(ticket_service)
    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id="call-db-failure",
                name=CREATE_TICKET_DRAFT,
                arguments={
                    "title": "数据库失败测试",
                    "description": "该草稿不应被报告为保存成功。",
                    "device_or_system": "测试系统",
                },
            ),
            final_tool_response(),
        ],
    )
    service = make_service(llm, tool_executor=executor)

    response = await service.run(
        message="创建一个会触发数据库失败的草稿。",
        conversation_id="conversation-db-failure",
    )

    assert response.status == "needs_clarification"
    assert response.ticket_draft is None
    assert "未成功" in (response.answer or "")
    assert response.error == "TICKET_PERSISTENCE_ERROR"


async def test_tool_call_limit_prevents_unbounded_loop(
    tmp_path: Path,
) -> None:
    repository, ticket_service, executor = make_ticket_dependencies(
        tmp_path / "tickets.db"
    )
    draft = await ticket_service.create(
        args=CreateTicketDraftArgs(
            title="查询循环测试",
            description="测试工具调用次数上限。",
            device_or_system="测试系统",
        ),
        idempotency_key="seed-tool-limit",
    )
    llm = FakeLLM(
        result=supervisor_result("ticket_request"),
        tool_results=[
            tool_response(
                call_id=f"call-get-{index}",
                name=GET_TICKET_DRAFT,
                arguments={"draft_id": draft.draft.id},
            )
            for index in range(4)
        ],
    )
    service = make_service(llm, tool_executor=executor)
    try:
        response = await service.run(
            message="反复查询这个工单草稿。",
            conversation_id="conversation-tool-limit",
        )

        assert response.status == "needs_clarification"
        assert response.error == "TOOL_CALL_LIMIT"
        assert len(response.tool_calls) == 3
        assert [call.tool_call_id for call in response.tool_calls] == [
            "call-get-0",
            "call-get-1",
            "call-get-2",
        ]
    finally:
        await repository.close()


async def test_ticket_draft_api_list_get_and_update(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    repository, ticket_service, _ = make_ticket_dependencies(
        tmp_path / "tickets.db"
    )
    app.dependency_overrides[get_ticket_service] = lambda: ticket_service
    try:
        created = await ticket_service.create(
            args=CreateTicketDraftArgs(
                title="VPN 无法连接",
                description="远程办公时 VPN 连接失败。",
                device_or_system="公司笔记本",
            ),
            idempotency_key="seed-api",
        )

        list_response = await client.get("/api/v1/tickets/drafts")
        get_response = await client.get(
            f"/api/v1/tickets/drafts/{created.draft.id}"
        )
        patch_response = await client.patch(
            f"/api/v1/tickets/drafts/{created.draft.id}",
            json={"description": "VPN 证书过期，需要重新登录。"},
        )

        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "draft"
        assert patch_response.status_code == 200
        assert "证书过期" in patch_response.json()["description"]
    finally:
        await repository.close()


async def test_supervisor_timeout_is_service_error_not_clarification(
    client: httpx.AsyncClient,
) -> None:
    from app.core.exceptions import LLMTimeoutError

    service = make_service(FakeLLM(error=LLMTimeoutError()))
    app.dependency_overrides[get_agent_service] = lambda: service

    response = await client.post(
        "/api/v1/agent/run",
        json={"message": "帮我处理一下这个问题"},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "LLM_TIMEOUT"

