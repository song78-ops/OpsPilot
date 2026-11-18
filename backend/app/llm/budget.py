"""Process-level request, token, and cost guard for paid LLM calls."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from app.core.exceptions import LLMBudgetExceededError, LLMDisabledError


@dataclass(frozen=True, slots=True)
class LLMBudgetLimits:
    enabled: bool
    max_requests: int
    max_tokens: int
    max_cost_usd: float
    max_output_tokens: int
    input_cost_per_million_usd: float
    output_cost_per_million_usd: float


@dataclass(frozen=True, slots=True)
class BudgetReservation:
    id: str
    estimated_prompt_tokens: int
    max_output_tokens: int


class LLMBudgetController:
    """Reserve conservative budgets before calls and record actual usage."""

    def __init__(self, limits: LLMBudgetLimits) -> None:
        self._limits = limits
        self._lock = asyncio.Lock()
        self._requests = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._reserved_tokens = 0
        self._reserved_cost_usd = 0.0
        self._cost_usd = 0.0
        self._blocked_requests = 0
        self._started_at = time.time()

    async def reserve(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> BudgetReservation:
        estimate = estimate_message_tokens(messages, tools=tools)
        async with self._lock:
            limits = self._limits
            if not limits.enabled:
                self._blocked_requests += 1
                raise LLMDisabledError()
            if self._requests + 1 > limits.max_requests:
                self._blocked_requests += 1
                raise LLMBudgetExceededError("请求次数达到上限")

            remaining_tokens = (
                limits.max_tokens
                - self._prompt_tokens
                - self._completion_tokens
                - self._reserved_tokens
            )
            output_tokens = min(
                limits.max_output_tokens,
                max(0, remaining_tokens - estimate),
            )
            if output_tokens <= 0:
                self._blocked_requests += 1
                raise LLMBudgetExceededError("Token 预算不足")

            projected_cost = self._cost_usd + self._reserved_cost_usd + (
                (
                    estimate * limits.input_cost_per_million_usd
                    + output_tokens * limits.output_cost_per_million_usd
                )
                / 1_000_000
            )
            if projected_cost > limits.max_cost_usd:
                self._blocked_requests += 1
                raise LLMBudgetExceededError("费用预算不足")

            reservation = BudgetReservation(
                id=uuid.uuid4().hex,
                estimated_prompt_tokens=estimate,
                max_output_tokens=output_tokens,
            )
            self._requests += 1
            self._reserved_tokens += estimate + output_tokens
            self._reserved_cost_usd += (
                estimate * limits.input_cost_per_million_usd
                + output_tokens * limits.output_cost_per_million_usd
            ) / 1_000_000
            return reservation

    async def finalize(
        self,
        reservation: BudgetReservation,
        *,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        async with self._lock:
            limits = self._limits
            self._reserved_tokens = max(
                0,
                self._reserved_tokens
                - reservation.estimated_prompt_tokens
                - reservation.max_output_tokens,
            )
            reserved_cost = (
                reservation.estimated_prompt_tokens
                * limits.input_cost_per_million_usd
                + reservation.max_output_tokens
                * limits.output_cost_per_million_usd
            ) / 1_000_000
            self._reserved_cost_usd = max(
                0.0,
                self._reserved_cost_usd - reserved_cost,
            )
            self._prompt_tokens += max(0, prompt_tokens)
            self._completion_tokens += max(0, completion_tokens)
            self._cost_usd += (
                max(0, prompt_tokens) * limits.input_cost_per_million_usd
                + max(0, completion_tokens)
                * limits.output_cost_per_million_usd
            ) / 1_000_000

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                **asdict(self._limits),
                "requests_used": self._requests,
                "prompt_tokens_used": self._prompt_tokens,
                "completion_tokens_used": self._completion_tokens,
                "total_tokens_used": (
                    self._prompt_tokens + self._completion_tokens
                ),
                "cost_usd_used": self._cost_usd,
                "reserved_tokens": self._reserved_tokens,
                "reserved_cost_usd": self._reserved_cost_usd,
                "blocked_requests": self._blocked_requests,
                "started_at": self._started_at,
                "token_budget_exceeded": (
                    self._prompt_tokens + self._completion_tokens
                    > self._limits.max_tokens
                ),
                "cost_budget_exceeded": (
                    self._cost_usd > self._limits.max_cost_usd
                ),
            }


def estimate_message_tokens(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Conservative pre-call token estimate based on serialized characters."""
    serialized = json.dumps(messages, ensure_ascii=False)
    tools_text = (
        json.dumps(tools, ensure_ascii=False) if tools is not None else ""
    )
    return max(1, len(serialized) + len(tools_text) + len(messages) * 8)
