"""Knowledge-base grounded answer API schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rag.retrieval.types import SearchMode
from app.schemas.chat import TokenUsage


class RagAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4_000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    mode: SearchMode = SearchMode.HYBRID
    rerank: bool = False
    candidate_k: int | None = Field(default=None, ge=1, le=100)
    document_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{32}$",
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class RagSourceResponse(BaseModel):
    citation_id: int
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    part_index: int
    content_excerpt: str


class RagLatencyResponse(BaseModel):
    retrieval_ms: float
    context_ms: float
    generation_ms: float
    total_ms: float


class RagAskResponse(BaseModel):
    answer: str | None
    status: Literal["answered", "insufficient_evidence"]
    reason: str | None
    sources: list[RagSourceResponse]
    retrieval_mode: SearchMode
    rerank_applied: bool
    retrieval_count: int
    model: str | None
    usage: TokenUsage | None
    latency_ms: RagLatencyResponse

