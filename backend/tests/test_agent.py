"""LangGraph agent routing and state tests."""

import json
from pathlib import Path

import httpx
import pytest

from app.agents.nodes import AgentNodes
from app.agents.service import AgentService
from app.agents.workflow import AgentWorkflow
from app.api.deps import get_agent_service
from app.core.exceptions import LLMTimeoutError
from app.llm.base import LLMResult
from app.main import app
from app.rag.exceptions import AgentNodeExecutionError
from app.rag.retrieval.types import SearchMode
from app.schemas.chat import ChatResponse, TokenUsage
from app.schemas.rag import (
    RagAskResponse,
    RagLatencyResponse,
    RagSourceResponse,
)
from tests.fakes import FakeLLM


def llm_result(payload: dict, *, model: str = "fake-deepseek") -> LLMResult:
    return LLMResult(
        content=json.dumps(payload, ensure_ascii=False),
        model=model,
        prompt_tokens=20,
        completion_tokens=10,
    )


def supervisor_result(intent: str, *, question: str = "") -> LLMResult:
    return llm_result(
        {
            "intent": intent,
            "reason": f"classified as {intent}",
            "clarification_question": question,
        }
    )


def knowledge_response(
    *,
    status: str = "answered",
) -> RagAskResponse:
    source = RagSourceResponse(
        citation_id=1,
        document_id="a" * 32,
        chunk_id=f"{'a' * 32}:0001",
        filename="redis.txt",
        page_number=3,
        part_index=1,
        content_excerpt="Redis 使用互斥锁处理缓存击穿。",
    )
    return RagAskResponse(
        answer="Redis 使用互斥锁[1]。" if status == "answered" else None,
        status=status,
        reason=(
            "证据支持"
            if status == "answered"
            else "知识库没有充分依据"
        ),
        sources=[source] if status == "answered" else [],
        retrieval_mode=SearchMode.HYBRID,
        rerank_applied=False,
        retrieval_count=1,
        model="fake-rag-model",
        usage=TokenUsage(prompt_tokens=50, completion_tokens=20),
        latency_ms=RagLatencyResponse(
            retrieval_ms=2,
            context_ms=1,
            generation_ms=8,
            total_ms=11,
        ),
    )


class StaticRagService:
    def __init__(
        self,
        *,
        response: RagAskResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or knowledge_response()
        self.error = error
        self.calls = []

    async def ask(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class StaticChatService:
    def __init__(
        self,
        *,
        answer: str = "你好，我是 OpsPilot。",
        error: Exception | None = None,
    ) -> None:
        self.answer_text = answer
        self.error = error
        self.calls = []
        self.history_contexts = []

    async def answer(
        self,
        message: str,
        *,
        history_context: str = "",
    ) -> ChatResponse:
        self.calls.append(message)
        self.history_contexts.append(history_context)
        if self.error is not None:
            raise self.error
        return ChatResponse(
            answer=self.answer_text,
            model="fake-chat-model",
            usage=TokenUsage(prompt_tokens=15, completion_tokens=8),
        )


def make_service(
    llm: FakeLLM,
    *,
    rag: StaticRagService | None = None,
    chat: StaticChatService | None = None,
    tool_executor=None,
) -> AgentService:
    nodes = AgentNodes(
        llm=llm,
        rag_service=rag or StaticRagService(),
        chat_service=chat or StaticChatService(),
        ticket_tool_executor=tool_executor or object(),
        supervisor_prompt="只做意图分类。",
        ticket_prompt="只生成工单草稿。",
        max_tool_calls=3,
    )
    return AgentService(
        workflow=AgentWorkflow(
            nodes=nodes,
            max_execution_steps=10,
        )
    )


async def test_knowledge_intent_executes_rag_node() -> None:
    rag = StaticRagService()
    chat = StaticChatService()
    service = make_service(
        FakeLLM(result=supervisor_result("knowledge_query")),
        rag=rag,
        chat=chat,
    )

    response = await service.run(
        message="Redis 缓存击穿怎么处理？",
        conversation_id="c1",
    )

    assert response.intent == "knowledge_query"
    assert response.status == "completed"
    assert response.answer == "Redis 使用互斥锁[1]。"
    assert response.sources[0].filename == "redis.txt"
    assert response.executed_nodes == ["supervisor", "knowledge"]
    assert len(rag.calls) == 1
    assert chat.calls == []
    assert response.conversation_id == "c1"
    assert response.memory_persisted is False


async def test_general_chat_intent_reuses_chat_service() -> None:
    rag = StaticRagService()
    chat = StaticChatService(answer="你好，我是 OpsPilot。")
    service = make_service(
        FakeLLM(result=supervisor_result("general_chat")),
        rag=rag,
        chat=chat,
    )

    response = await service.run(
        message="你好，介绍一下自己。",
        conversation_id=None,
    )

    assert response.intent == "general_chat"
    assert response.status == "completed"
    assert response.answer == "你好，我是 OpsPilot。"
    assert response.executed_nodes == ["supervisor", "chat"]
    assert chat.calls == ["你好，介绍一下自己。"]
    assert rag.calls == []


async def test_clarification_intent_only_executes_safe_node() -> None:
    rag = StaticRagService()
    chat = StaticChatService()
    llm = FakeLLM(
        result=supervisor_result(
            "clarification",
            question="请说明要查询知识还是创建工单？",
        )
    )
    service = make_service(llm, rag=rag, chat=chat)

    response = await service.run(
        message="帮我处理一下这个问题。",
        conversation_id=None,
    )

    assert response.intent == "clarification"
    assert response.status == "needs_clarification"
    assert response.answer == "请说明要查询知识还是创建工单？"
    assert response.executed_nodes == ["supervisor", "clarification"]
    assert rag.calls == []
    assert chat.calls == []


@pytest.mark.parametrize(
    "content",
    [
        "这不是 JSON",
        '{"intent":"delete_everything","reason":"bad"}',
        '{"intent":"ticket_request"}',
    ],
)
async def test_invalid_supervisor_output_fails_safe(content: str) -> None:
    llm = FakeLLM(
        result=LLMResult(
            content=content,
            model="fake-deepseek",
        )
    )
    rag = StaticRagService()
    chat = StaticChatService()
    service = make_service(llm, rag=rag, chat=chat)

    response = await service.run(
        message="模糊请求",
        conversation_id=None,
    )

    assert response.intent == "clarification"
    assert response.status == "needs_clarification"
    assert response.error == "SUPERVISOR_INVALID_OUTPUT"
    assert rag.calls == []
    assert chat.calls == []


async def test_supervisor_timeout_routes_to_clarification() -> None:
    service = make_service(FakeLLM(error=LLMTimeoutError()))

    with pytest.raises(LLMTimeoutError):
        await service.run(
            message="帮我处理问题",
            conversation_id=None,
        )


async def test_insufficient_knowledge_does_not_fall_back_to_chat() -> None:
    rag = StaticRagService(
        response=knowledge_response(status="insufficient_evidence")
    )
    chat = StaticChatService()
    service = make_service(
        FakeLLM(result=supervisor_result("knowledge_query")),
        rag=rag,
        chat=chat,
    )

    response = await service.run(
        message="公司年假余额是多少？",
        conversation_id=None,
    )

    assert response.intent == "knowledge_query"
    assert response.status == "insufficient_evidence"
    assert response.answer is None
    assert response.sources == []
    assert chat.calls == []


async def test_node_exception_is_mapped_to_agent_error(
    client: httpx.AsyncClient,
) -> None:
    service = make_service(
        FakeLLM(result=supervisor_result("knowledge_query")),
        rag=StaticRagService(error=RuntimeError("database exploded")),
    )
    app.dependency_overrides[get_agent_service] = lambda: service

    response = await client.post(
        "/api/v1/agent/run",
        json={"message": "Redis 缓存"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "AGENT_NODE_ERROR"


async def test_agent_api_returns_trace_and_usage(
    client: httpx.AsyncClient,
) -> None:
    service = make_service(
        FakeLLM(result=supervisor_result("knowledge_query"))
    )
    app.dependency_overrides[get_agent_service] = lambda: service

    response = await client.post(
        "/api/v1/agent/run",
        json={"message": "Redis 缓存", "conversation_id": "demo"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "knowledge_query"
    assert body["executed_nodes"] == ["supervisor", "knowledge"]
    assert body["memory_persisted"] is False
    assert len(body["node_traces"]) == 2
    assert body["usage"]["prompt_tokens"] == 70
    assert body["usage"]["completion_tokens"] == 30


async def test_agent_api_rejects_conflicting_request_ids(
    client: httpx.AsyncClient,
) -> None:
    service = make_service(
        FakeLLM(result=supervisor_result("general_chat"))
    )
    app.dependency_overrides[get_agent_service] = lambda: service

    response = await client.post(
        "/api/v1/agent/run",
        json={
            "message": "你好",
            "request_id": "body-request-id",
        },
        headers={"Idempotency-Key": "different-header-id"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AGENT_REQUEST_ID_CONFLICT"

