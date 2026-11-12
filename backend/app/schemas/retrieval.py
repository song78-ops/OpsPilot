"""Dense vector indexing and search schemas."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.rag.retrieval.types import (
    IndexSummary,
    RankedRetrievalHit,
    SearchMode,
)


class DocumentIndexResponse(BaseModel):
    document_id: str
    indexed_chunks: int
    indexed_parts: int
    embedding_model: str
    vector_dimension: int
    index_version: int
    collection_name: str

    @classmethod
    def from_domain(cls, summary: IndexSummary) -> "DocumentIndexResponse":
        return cls(
            document_id=summary.document_id,
            indexed_chunks=summary.indexed_chunks,
            indexed_parts=summary.indexed_parts,
            embedding_model=summary.embedding_model,
            vector_dimension=summary.vector_dimension,
            index_version=summary.index_version,
            collection_name=summary.collection_name,
        )


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4_000)
    top_k: int | None = Field(default=None, ge=1, le=100)
    mode: SearchMode = SearchMode.DENSE
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


class RetrievalHitResponse(BaseModel):
    rank: int
    score: float
    mode: str
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    part_index: int
    part_count: int
    dense_rank: int | None = None
    dense_score: float | None = None
    bm25_rank: int | None = None
    bm25_score: float | None = None
    retrieval_rank: int | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None

    @classmethod
    def from_domain(cls, hit: RankedRetrievalHit) -> "RetrievalHitResponse":
        return cls(
            rank=hit.rank,
            score=hit.final_score,
            mode=hit.mode,
            document_id=hit.unit.document_id,
            chunk_id=hit.unit.chunk_id,
            filename=hit.unit.filename,
            page_number=hit.unit.page_number,
            chunk_index=hit.unit.chunk_index,
            content=hit.unit.content,
            part_index=hit.unit.part_index,
            part_count=hit.unit.part_count,
            dense_rank=hit.dense_rank,
            dense_score=hit.dense_score,
            bm25_rank=hit.bm25_rank,
            bm25_score=hit.bm25_score,
            retrieval_rank=(
                hit.retrieval_rank
                if hit.retrieval_rank is not None
                else hit.rank
            ),
            retrieval_score=(
                hit.retrieval_score
                if hit.retrieval_score is not None
                else hit.final_score
            ),
            rerank_score=hit.rerank_score,
        )


class RetrievalSearchResponse(BaseModel):
    query: str
    embedding_model: str
    vector_dimension: int
    index_version: int
    top_k: int
    mode: SearchMode
    rrf_k: int | None = None
    rerank_requested: bool
    rerank_applied: bool
    rerank_model: str | None = None
    candidate_k: int
    items: list[RetrievalHitResponse]

