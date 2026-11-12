"""Provider-independent embedding interface."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EmbeddingModelInfo:
    """Identity and limits for a loaded embedding model."""

    name: str
    dimension: int
    max_tokens: int
    query_instruction: str


class EmbeddingProvider(Protocol):
    """Embedding operations required by document indexing and search."""

    @property
    def info(self) -> EmbeddingModelInfo:
        """Return model identity and dimensions."""
        ...

    def count_tokens(self, text: str) -> int:
        """Count model tokens including special tokens."""
        ...

    def split_text(self, text: str) -> list[str]:
        """Split text safely when it exceeds the model token limit."""
        ...

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed passages without the retrieval query instruction."""
        ...

    def encode_query(self, query: str) -> list[float]:
        """Embed a query with the BGE retrieval instruction."""
        ...

