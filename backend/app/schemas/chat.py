"""Chat request and response models."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    """A user question accepted by the chat endpoints."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=12_000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class TokenUsage(BaseModel):
    """Token counts returned by the model provider."""

    prompt_tokens: int = 0
    completion_tokens: int = 0


class ChatResponse(BaseModel):
    """Model answer and basic usage metadata."""

    answer: str
    model: str
    usage: TokenUsage | None = None


class ChatStreamEvent(BaseModel):
    """A provider-independent event emitted during streamed answering."""

    event: Literal["meta", "token", "usage", "done", "error"]
    data: dict[str, Any]

