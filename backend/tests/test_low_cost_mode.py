"""Low-cost provider and paid-call budget regression tests."""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.api.deps import get_llm_client
from app.core.config import Settings, get_settings
from app.core.exceptions import LLMBudgetExceededError, LLMDisabledError
from app.llm.budget import LLMBudgetController, LLMBudgetLimits
from app.llm.deepseek import DeepSeekLLM
from app.llm.mock import MockLLM
from app.main import app


class BudgetCompletions:
    def __init__(
        self,
        *,
        prompt_tokens: int = 12,
        completion_tokens: int = 5,
    ) -> None:
        self.calls = 0
        self.request_kwargs: list[dict] = []
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens

    async def create(self, **kwargs):
        self.calls += 1
        self.request_kwargs.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="budgeted answer")
                )
            ],
            model="fake-deepseek",
            usage=SimpleNamespace(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
            ),
        )


class BudgetClient:
    def __init__(self, completions: BudgetCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)

    async def close(self) -> None:
        pass


def budget_controller(
    *,
    requests: int = 10,
    tokens: int = 10_000,
    cost: float = 10.0,
    output_tokens: int = 100,
    input_rate: float = 0.0,
    output_rate: float = 0.0,
) -> LLMBudgetController:
    return LLMBudgetController(
        LLMBudgetLimits(
            enabled=True,
            max_requests=requests,
            max_tokens=tokens,
            max_cost_usd=cost,
            max_output_tokens=output_tokens,
            input_cost_per_million_usd=input_rate,
            output_cost_per_million_usd=output_rate,
        )
    )


@pytest.mark.asyncio
async def test_default_provider_selection_uses_mock_without_api_key() -> None:
    settings = Settings(
        llm_provider="mock",
        deepseek_api_key=None,
    )
    dependency = get_llm_client(settings)
    client = await anext(dependency)

    assert isinstance(client, MockLLM)
    await dependency.aclose()


@pytest.mark.asyncio
async def test_mock_generates_ticket_tool_call_and_grounded_answer() -> None:
    mock = MockLLM()
    supervisor = await mock.generate(
        system_prompt="你是 Supervisor，负责判断意图。",
        user_message=(
            "<current_user_request>帮我创建一个电脑无法联网的工单"
            "</current_user_request>"
        ),
    )
    assert json.loads(supervisor.content)["intent"] == "ticket_request"

    tool_response = await mock.generate_with_tools(
        messages=[
            {
                "role": "system",
                "content": "工单助手 <trusted_ticket_context></trusted_ticket_context>",
            },
            {"role": "user", "content": "帮我创建一个电脑无法联网的工单。"},
        ],
        tools=[{"type": "function", "function": {"name": "create_ticket_draft"}}],
    )
    assert tool_response.tool_calls[0].name == "create_ticket_draft"
    assert tool_response.prompt_tokens == 0

    rag = await mock.generate(
        system_prompt=(
            "你是 OpsPilot 企业知识库问答助手。"
            "<knowledge_evidence>"
        ),
        user_message=(
            "<question>缓存击穿怎么处理？</question>"
            "<knowledge_evidence>[1] Source: redis.txt\n"
            "缓存击穿可以使用互斥锁和逻辑过期。</knowledge_evidence>"
        ),
    )
    payload = json.loads(rag.content)
    assert payload["status"] == "answered"
    assert payload["used_citations"] == [1]
    assert rag.completion_tokens == 0


@pytest.mark.asyncio
async def test_request_budget_blocks_before_second_paid_call() -> None:
    completions = BudgetCompletions()
    budget = budget_controller(requests=1)
    llm = DeepSeekLLM(
        api_key="not-real",
        base_url="https://example.invalid",
        model="fake",
        timeout_seconds=1,
        max_retries=0,
        temperature=0,
        client=BudgetClient(completions),
        budget=budget,
    )

    await llm.generate(system_prompt="system", user_message="hello")
    with pytest.raises(LLMBudgetExceededError):
        await llm.generate(system_prompt="system", user_message="again")

    assert completions.calls == 1
    snapshot = await budget.snapshot()
    assert snapshot["requests_used"] == 1
    assert snapshot["blocked_requests"] == 1


@pytest.mark.asyncio
async def test_token_and_cost_budgets_block_subsequent_calls() -> None:
    token_completions = BudgetCompletions(
        prompt_tokens=600,
        completion_tokens=500,
    )
    token_budget = budget_controller(tokens=1_000)
    token_llm = DeepSeekLLM(
        api_key="not-real",
        base_url="https://example.invalid",
        model="fake",
        timeout_seconds=1,
        max_retries=0,
        temperature=0,
        client=BudgetClient(token_completions),
        budget=token_budget,
    )
    await token_llm.generate(system_prompt="system", user_message="hello")
    with pytest.raises(LLMBudgetExceededError):
        await token_llm.generate(system_prompt="system", user_message="again")
    token_snapshot = await token_budget.snapshot()
    assert token_snapshot["total_tokens_used"] == 1_100
    assert token_snapshot["token_budget_exceeded"] is True

    cost_completions = BudgetCompletions(
        prompt_tokens=600,
        completion_tokens=500,
    )
    cost_budget = budget_controller(
        tokens=10_000,
        cost=0.00012,
        output_tokens=10,
        input_rate=1.0,
        output_rate=1.0,
    )
    cost_llm = DeepSeekLLM(
        api_key="not-real",
        base_url="https://example.invalid",
        model="fake",
        timeout_seconds=1,
        max_retries=0,
        temperature=0,
        client=BudgetClient(cost_completions),
        budget=cost_budget,
    )
    await cost_llm.generate(system_prompt="system", user_message="hello")
    with pytest.raises(LLMBudgetExceededError):
        await cost_llm.generate(system_prompt="system", user_message="again")
    cost_snapshot = await cost_budget.snapshot()
    assert cost_snapshot["cost_budget_exceeded"] is True


@pytest.mark.asyncio
async def test_disabled_budget_never_initializes_paid_or_mock_call() -> None:
    budget = LLMBudgetController(
        LLMBudgetLimits(
            enabled=False,
            max_requests=0,
            max_tokens=0,
            max_cost_usd=0,
            max_output_tokens=1,
            input_cost_per_million_usd=0,
            output_cost_per_million_usd=0,
        )
    )

    with pytest.raises(LLMDisabledError):
        await budget.reserve(messages=[{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_api_uses_mock_provider_and_zero_token_usage(
    client: httpx.AsyncClient,
) -> None:
    settings = Settings(
        llm_provider="mock",
        deepseek_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    response = await client.post(
        "/api/v1/chat",
        json={"message": "你好"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "mock-local"
    assert body["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }


@pytest.mark.asyncio
async def test_budget_health_endpoint_has_limits_and_no_secret(
    client: httpx.AsyncClient,
) -> None:
    settings = Settings(
        llm_provider="deepseek",
        real_llm_max_requests=3,
        real_llm_max_tokens=5_000,
        real_llm_max_cost_usd=0.01,
        real_llm_input_cost_per_million_usd=0.1,
        real_llm_output_cost_per_million_usd=0.2,
    )
    app.dependency_overrides[get_settings] = lambda: settings

    response = await client.get("/api/v1/health/llm-budget")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deepseek"
    assert body["budget"]["max_requests"] == 3
    assert body["budget"]["max_tokens"] == 5_000
    assert "api_key" not in str(body).lower()
