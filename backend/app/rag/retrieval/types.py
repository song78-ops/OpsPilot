"""Dense retrieval data structures."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalUnit:
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    part_index: int
    part_count: int
    original_chunk_char_count: int

    @property
    def key(self) -> str:
        return f"{self.document_id}:{self.chunk_id}:{self.part_index}"


@dataclass(frozen=True, slots=True)
class VectorPoint:
    point_id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SearchHit:
    score: float
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    part_index: int
    part_count: int
    original_chunk_char_count: int

    @property
    def key(self) -> str:
        return f"{self.document_id}:{self.chunk_id}:{self.part_index}"

    def to_unit(self) -> RetrievalUnit:
        return RetrievalUnit(
            document_id=self.document_id,
            chunk_id=self.chunk_id,
            filename=self.filename,
            page_number=self.page_number,
            chunk_index=self.chunk_index,
            content=self.content,
            part_index=self.part_index,
            part_count=self.part_count,
            original_chunk_char_count=self.original_chunk_char_count,
        )


@dataclass(frozen=True, slots=True)
class BM25Hit:
    score: float
    unit: RetrievalUnit


@dataclass(frozen=True, slots=True)
class RankedRetrievalHit:
    rank: int
    final_score: float
    mode: str
    unit: RetrievalUnit
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    retrieval_rank: int | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None


class SearchMode(str, Enum):
    DENSE = "dense"
    BM25 = "bm25"
    HYBRID = "hybrid"


@dataclass(frozen=True, slots=True)
class IndexSummary:
    document_id: str
    indexed_chunks: int
    indexed_parts: int
    embedding_model: str
    vector_dimension: int
    index_version: int
    collection_name: str

