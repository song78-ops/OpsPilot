"""Provider-independent reranker interface."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RerankerModelInfo:
    name: str
    max_length: int


@dataclass(frozen=True, slots=True)
class RerankScore:
    score: float
    inferred_part_count: int


class RerankerProvider(Protocol):
    """CrossEncoder operations required by reranked retrieval."""

    @property
    def info(self) -> RerankerModelInfo:
        ...

    def score_pairs(
        self,
        query: str,
        documents: list[str],
    ) -> list[RerankScore]:
        """Score query-document pairs in batches."""
        ...

