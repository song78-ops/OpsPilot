"""DeepSeek adapter tests without network access."""

from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError

from app.core.exceptions import LLMTimeoutError
from app.llm.deepseek import DeepSeekLLM


class FakeCompletions:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def create(self, **kwargs):
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="DeepSeek fake answer")
                )
            ],
            model="deepseek-chat",
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
        )


class FakeOpenAIClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(error=error))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeAsyncStream:
    def __init__(self) -> None:
        self.chunks = iter(
            [
                SimpleNamespace(
                    model="deepseek-chat",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="第一段")
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    model="deepseek-chat",
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="第二段")
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    model="deepseek-chat",
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=18,
                        completion_tokens=9,
                    ),
                ),
            ]
        )
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


class FakeStreamingCompletions:
    def __init__(self) -> None:
        self.response = FakeAsyncStream()

    async def create(self, **kwargs):
        assert kwargs["stream"] is True
        assert kwargs["stream_options"] == {"include_usage": True}
        return self.response


class FakeStreamingClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeStreamingCompletions())

    async def close(self) -> None:
        pass


async def test_deepseek_adapter_normalizes_completion() -> None:
    fake_client = FakeOpenAIClient()
    llm = DeepSeekLLM(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=10,
        max_retries=0,
        temperature=0.2,
        client=fake_client,
    )

    result = await llm.generate(
        system_prompt="system",
        user_message="hello",
    )

    assert result.content == "DeepSeek fake answer"
    assert result.model == "deepseek-chat"
    assert result.prompt_tokens == 12
    assert result.completion_tokens == 5

    await llm.aclose()
    assert fake_client.closed is True


async def test_deepseek_adapter_maps_timeout() -> None:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    fake_client = FakeOpenAIClient(error=APITimeoutError(request=request))
    llm = DeepSeekLLM(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=10,
        max_retries=0,
        temperature=0.2,
        client=fake_client,
    )

    with pytest.raises(LLMTimeoutError):
        await llm.generate(system_prompt="system", user_message="hello")


async def test_deepseek_adapter_streams_text_and_usage() -> None:
    fake_client = FakeStreamingClient()
    llm = DeepSeekLLM(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        timeout_seconds=10,
        max_retries=0,
        temperature=0.2,
        client=fake_client,
    )

    chunks = [
        chunk
        async for chunk in llm.stream(
            system_prompt="system",
            user_message="hello",
        )
    ]

    assert "".join(chunk.text for chunk in chunks) == "第一段第二段"
    assert chunks[-1].prompt_tokens == 18
    assert chunks[-1].completion_tokens == 9
    assert fake_client.chat.completions.response.closed is True

