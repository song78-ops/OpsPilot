"""SSE chat tests using an in-process Fake LLM."""

import json
from collections.abc import AsyncIterator

import httpx

from app.api.deps import get_llm_client
from app.core.exceptions import LLMTimeoutError
from app.llm.base import LLMStreamChunk
from app.main import app
from app.services.chat_service import ChatService
from tests.fakes import FakeLLM


def override_llm(fake_llm: FakeLLM):
    async def dependency() -> AsyncIterator[FakeLLM]:
        yield fake_llm

    return dependency


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        lines = block.splitlines()
        event_name = next(line[7:] for line in lines if line.startswith("event: "))
        data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((event_name, json.loads(data)))
    return events


async def test_stream_returns_incremental_events(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_llm_client] = override_llm(FakeLLM())

    response = await client.post(
        "/api/v1/chat/stream",
        json={"message": "什么是 RAG？"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"

    events = parse_sse(response.text)
    assert [name for name, _ in events] == [
        "meta",
        "token",
        "token",
        "usage",
        "done",
    ]
    assert events[0][1]["model"] == "deepseek-chat"
    assert events[0][1]["request_id"] == events[-1][1]["request_id"]
    assert "".join(data["text"] for name, data in events if name == "token") == (
        "RAG 是检索增强生成。"
    )
    assert events[3][1] == {
        "prompt_tokens": 20,
        "completion_tokens": 10,
    }


async def test_stream_omits_usage_when_upstream_does_not_provide_it(
    client: httpx.AsyncClient,
) -> None:
    fake_llm = FakeLLM(
        stream_chunks=[LLMStreamChunk(text="第一段"), LLMStreamChunk(text="第二段")]
    )
    app.dependency_overrides[get_llm_client] = override_llm(fake_llm)

    response = await client.post(
        "/api/v1/chat/stream",
        json={"message": "测试无 usage"},
    )

    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["meta", "token", "token", "done"]


async def test_stream_emits_error_after_meta_and_keeps_http_200(
    client: httpx.AsyncClient,
) -> None:
    fake_llm = FakeLLM(
        stream_chunks=[LLMStreamChunk(text="部分回答")],
        error=LLMTimeoutError(),
    )
    app.dependency_overrides[get_llm_client] = override_llm(fake_llm)

    response = await client.post(
        "/api/v1/chat/stream",
        json={"message": "测试流式中断"},
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["meta", "token", "error"]
    assert events[-1][1]["code"] == "LLM_TIMEOUT"
    assert fake_llm.stream_closed is True


async def test_closing_consumer_closes_provider_stream() -> None:
    fake_llm = FakeLLM(
        stream_chunks=[LLMStreamChunk(text="第一段"), LLMStreamChunk(text="第二段")]
    )
    service = ChatService(
        llm=fake_llm,
        system_prompt="system prompt",
        model_name="fake-deepseek",
    )

    stream = service.stream_answer("hello", request_id="test-request")
    assert (await anext(stream)).event == "meta"
    assert (await anext(stream)).event == "token"
    await stream.aclose()

    assert fake_llm.stream_closed is True
