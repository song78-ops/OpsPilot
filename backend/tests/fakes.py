"""Deterministic fakes for tests that must not call DeepSeek."""

from collections.abc import AsyncIterator
import math

from app.llm.base import LLMResult, LLMStreamChunk
from app.rag.embeddings.base import EmbeddingModelInfo
from app.rag.reranking.base import RerankerModelInfo, RerankScore


class FakeLLM:
    """An LLMProvider with configurable output or error."""

    def __init__(
        self,
        *,
        result: LLMResult | None = None,
        error: Exception | None = None,
        stream_chunks: list[LLMStreamChunk] | None = None,
    ) -> None:
        self.result = result or LLMResult(
            content="RAG 是检索增强生成。",
            model="fake-deepseek",
            prompt_tokens=20,
            completion_tokens=10,
        )
        self.error = error
        self.stream_chunks = stream_chunks or [
            LLMStreamChunk(text="RAG "),
            LLMStreamChunk(text="是检索增强生成。"),
            LLMStreamChunk(prompt_tokens=20, completion_tokens=10),
        ]
        self.closed = False
        self.stream_closed = False
        self.generate_calls = 0
        self.last_system_prompt = ""
        self.last_user_message = ""

    async def generate(self, *, system_prompt: str, user_message: str) -> LLMResult:
        assert system_prompt
        assert user_message
        self.generate_calls += 1
        self.last_system_prompt = system_prompt
        self.last_user_message = user_message
        if self.error is not None:
            raise self.error
        return self.result

    async def stream(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        assert system_prompt
        assert user_message
        try:
            for chunk in self.stream_chunks:
                yield chunk
            if self.error is not None:
                raise self.error
        finally:
            self.stream_closed = True

    async def aclose(self) -> None:
        self.closed = True


class FakeEmbeddingModel:
    """Small deterministic embedding model with optional strict token limits."""

    def __init__(
        self,
        *,
        dimension: int = 6,
        actual_dimension: int | None = None,
        max_tokens: int = 500,
        overlap_tokens: int = 0,
    ) -> None:
        self._dimension = dimension
        self._actual_dimension = actual_dimension or dimension
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens

    @property
    def info(self) -> EmbeddingModelInfo:
        return EmbeddingModelInfo(
            name="fake-bge-small-zh-v1.5",
            dimension=self._dimension,
            max_tokens=self._max_tokens,
            query_instruction="",
        )

    def count_tokens(self, text: str) -> int:
        return len(text)

    def split_text(self, text: str) -> list[str]:
        if len(text) <= self._max_tokens:
            return [text]
        step = max(1, self._max_tokens - self._overlap_tokens)
        return [
            text[start : start + self._max_tokens]
            for start in range(0, len(text), step)
            if text[start : start + self._max_tokens]
        ]

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def encode_query(self, query: str) -> list[float]:
        return self._vector(query)

    def _vector(self, text: str) -> list[float]:
        lowered = text.lower()
        groups = [
            ("redis", "缓存", "cache"),
            ("mysql", "数据库", "订单", "事务"),
            ("rag", "知识库", "检索", "向量"),
            ("安全", "密钥", "权限"),
            ("工单", "审批", "故障"),
        ]
        vector = [0.05] * self._actual_dimension
        for index, keywords in enumerate(groups[: self._actual_dimension]):
            vector[index] += sum(
                2.0 for keyword in keywords if keyword in lowered
            )
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class FakeReranker:
    """Deterministic reranker that records batched invocations."""

    def __init__(
        self,
        *,
        scores: list[float] | None = None,
        keyword_scores: dict[str, float] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._scores = scores
        self._keyword_scores = keyword_scores or {}
        self._error = error
        self.calls: list[list[str]] = []

    @property
    def info(self) -> RerankerModelInfo:
        return RerankerModelInfo(
            name="fake-bge-reranker-base",
            max_length=512,
        )

    def score_pairs(
        self,
        query: str,
        documents: list[str],
    ) -> list[RerankScore]:
        self.calls.append(list(documents))
        if self._error is not None:
            raise self._error
        if self._scores is not None:
            return [
                RerankScore(score=score, inferred_part_count=1)
                for score in self._scores[: len(documents)]
            ]
        return [
            RerankScore(
                score=sum(
                    weight
                    for keyword, weight in self._keyword_scores.items()
                    if keyword.lower() in document.lower()
                ),
                inferred_part_count=1,
            )
            for document in documents
        ]


