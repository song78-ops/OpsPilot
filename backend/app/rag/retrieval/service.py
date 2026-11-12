"""Dense vector indexing and semantic search use cases."""

import asyncio
import uuid

from app.rag.embeddings.base import EmbeddingModelInfo, EmbeddingProvider
from app.rag.exceptions import (
    DocumentNotIndexedError,
    EmbeddingDimensionError,
    InvalidRetrievalParameterError,
    QueryTokenLimitError,
)
from app.rag.retrieval.qdrant import QdrantVectorStore
from app.rag.retrieval.types import (
    IndexSummary,
    RetrievalUnit,
    SearchHit,
    VectorPoint,
)
from app.rag.retrieval.units import build_retrieval_units
from app.rag.service import DocumentService
from app.rag.types import DocumentRecord

_POINT_NAMESPACE = uuid.UUID("7d6e93b7-8294-4f16-9279-56b99e7b9430")


class DenseRetrievalService:
    """Embed immutable document chunks and query the active vector collection."""

    def __init__(
        self,
        *,
        document_service: DocumentService,
        embedding: EmbeddingProvider,
        vector_store: QdrantVectorStore,
        index_version: int,
        default_top_k: int,
        max_top_k: int,
    ) -> None:
        self._document_service = document_service
        self._embedding = embedding
        self._vector_store = vector_store
        self._index_version = index_version
        self._default_top_k = default_top_k
        self._max_top_k = max_top_k

    @property
    def model_info(self) -> EmbeddingModelInfo:
        return self._embedding.info

    @property
    def index_version(self) -> int:
        return self._index_version

    @property
    def embedding(self) -> EmbeddingProvider:
        return self._embedding

    @property
    def default_top_k(self) -> int:
        return self._default_top_k

    async def index_document(self, document_id: str) -> IndexSummary:
        record = await self._document_service.get_document(document_id)
        return await asyncio.to_thread(self._index_sync, record)

    async def search(
        self,
        *,
        query: str,
        top_k: int,
        document_id: str | None = None,
    ) -> list[SearchHit]:
        if top_k < 1 or top_k > self._max_top_k:
            raise InvalidRetrievalParameterError(
                f"top_k must be between 1 and {self._max_top_k}"
            )
        if document_id:
            await self._document_service.get_document(document_id)
        return await asyncio.to_thread(
            self.search_sync,
            query,
            top_k,
            document_id,
        )

    def _index_sync(self, record: DocumentRecord) -> IndexSummary:
        units = build_retrieval_units(record, self._embedding)
        return self.index_units(record, units)

    def index_units(
        self,
        record: DocumentRecord,
        units: list[RetrievalUnit],
    ) -> IndexSummary:
        """Embed and upsert already prepared retrieval units."""
        model_info = self._embedding.info
        texts = [unit.content for unit in units]

        vectors = self._embedding.encode_documents(texts)
        if len(vectors) != len(texts):
            raise EmbeddingDimensionError(len(texts), len(vectors))

        points: list[VectorPoint] = []
        for unit, vector in zip(units, vectors, strict=True):
            if len(vector) != model_info.dimension:
                raise EmbeddingDimensionError(
                    model_info.dimension,
                    len(vector),
                )
            stable_key = (
                f"{record.document_id}:{unit.chunk_id}:"
                f"{unit.part_index}:{self._index_version}"
            )
            points.append(
                VectorPoint(
                    point_id=str(uuid.uuid5(_POINT_NAMESPACE, stable_key)),
                    vector=vector,
                    payload={
                        "document_id": unit.document_id,
                        "chunk_id": unit.chunk_id,
                        "filename": unit.filename,
                        "page_number": unit.page_number,
                        "chunk_index": unit.chunk_index,
                        "content": unit.content,
                        "part_index": unit.part_index,
                        "part_count": unit.part_count,
                        "original_chunk_char_count": (
                            unit.original_chunk_char_count
                        ),
                        "embedding_model": model_info.name,
                        "embedding_dimension": model_info.dimension,
                        "index_version": self._index_version,
                    },
                )
            )

        self._vector_store.upsert(points)
        return IndexSummary(
            document_id=record.document_id,
            indexed_chunks=record.chunk_count,
            indexed_parts=len(points),
            embedding_model=model_info.name,
            vector_dimension=model_info.dimension,
            index_version=self._index_version,
            collection_name=self._vector_store.collection_name,
        )

    def search_sync(
        self,
        query: str,
        top_k: int,
        document_id: str | None,
    ) -> list[SearchHit]:
        model_info = self._embedding.info
        instructed_query = (
            f"{model_info.query_instruction}{query}"
            if model_info.query_instruction
            else query
        )
        token_count = self._embedding.count_tokens(instructed_query)
        if token_count > model_info.max_tokens:
            raise QueryTokenLimitError(token_count, model_info.max_tokens)

        query_vector = self._embedding.encode_query(query)
        if len(query_vector) != model_info.dimension:
            raise EmbeddingDimensionError(
                model_info.dimension,
                len(query_vector),
            )
        hits = self._vector_store.search(
            vector=query_vector,
            top_k=top_k,
            document_id=document_id,
        )
        if not hits and document_id:
            raise DocumentNotIndexedError(document_id)
        return hits

