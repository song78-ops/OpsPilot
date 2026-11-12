"""Provider-independent language model interface."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Normalized output from a chat completion."""

    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    """Normalized incremental output from a streaming completion."""

    text: str = ""
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Normalized tool call returned by an OpenAI-compatible provider."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class LLMToolResponse:
    """Non-streaming completion that may contain tool calls."""

    content: str | None
    model: str
    tool_calls: tuple[LLMToolCall, ...] = ()
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    """Minimal interface required by the chat use case."""

    async def generate(self, *, system_prompt: str, user_message: str) -> LLMResult:
        """Generate a single non-streaming response."""
        ...

    def stream(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Yield incremental response text and optional usage data."""
        ...

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMToolResponse:
        """Generate with native OpenAI-compatible function calling."""
        ...

    async def aclose(self) -> None:
        """Release provider resources."""
        ...

