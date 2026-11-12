"""Chat API tests using an in-process Fake LLM."""

from collections.abc import AsyncIterator

import httpx

from app.api.deps import get_llm_client
from app.core.exceptions import LLMConnectionError, LLMTimeoutError
from app.main import app
from tests.fakes import FakeLLM


def override_llm(fake_llm: FakeLLM):
    async def dependency() -> AsyncIterator[FakeLLM]:
        yield fake_llm

    return dependency


async def test_chat_returns_fake_answer(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_llm_client] = override_llm(FakeLLM())

    response = await client.post(
        "/api/v1/chat",
        json={"message": "什么是 RAG？"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "RAG 是检索增强生成。",
        "model": "fake-deepseek",
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 10,
        },
    }


async def test_chat_rejects_blank_message(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_llm_client] = override_llm(FakeLLM())

    response = await client.post("/api/v1/chat", json={"message": "   "})

    assert response.status_code == 422


async def test_chat_maps_timeout_to_504(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_llm_client] = override_llm(
        FakeLLM(error=LLMTimeoutError())
    )

    response = await client.post(
        "/api/v1/chat",
        json={"message": "测试超时"},
    )

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "LLM_TIMEOUT"


async def test_chat_maps_network_error_to_502(client: httpx.AsyncClient) -> None:
    app.dependency_overrides[get_llm_client] = override_llm(
        FakeLLM(error=LLMConnectionError())
    )

    response = await client.post(
        "/api/v1/chat",
        json={"message": "测试网络错误"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_CONNECTION_ERROR"

