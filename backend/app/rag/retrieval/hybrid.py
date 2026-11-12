"""Unified dense, BM25, and RRF retrieval service."""

import asyncio

from app.rag.exceptions import (
    DocumentNotIndexedError,
    IndexIncompatibleError,
    InvalidRetrievalParameterError,
)
from app.rag.retrieval.bm25 import BM25IndexStore
from app.rag.retrieval.rrf import reciprocal_rank_fusion
from app.rag.retrieval.service import DenseRetrievalService
from app.rag.retrieval.types import (
    IndexSummary,
    RankedRetrievalHit,
    SearchMode,
)
from app.rag.retrieval.units import build_retrieval_units
from app.rag.service import DocumentService


class HybridRetrievalService:
    """Keep dense and lexical indexes synchronized through shared units."""

    def __init__(
        self,
        *,
        document_service: DocumentService,
        dense: DenseRetrievalService,
        bm25: BM25IndexStore,
        rrf_k: int,
        candidate_k: int,
        max_top_k: int,
    ) -> None:
        self._document_service = document_service
        self._dense = dense
        self._bm25 = bm25
        self._rrf_k = rrf_k
        self._candidate_k = candidate_k
        self._max_top_k = max_top_k

    @property
    def model_info(self):
        return self._dense.model_info

    @property
    def index_version(self) -> int:
        return self._dense.index_version

    @property
    def default_top_k(self) -> int:
        return self._dense.default_top_k

    @property
    def rrf_k(self) -> int:
        return self._rrf_k

    @property
    def max_top_k(self) -> int:
        return self._max_top_k

    async def index_document(self, document_id: str) -> IndexSummary:
        record = await self._document_service.get_document(document_id)
        return await asyncio.to_thread(self._index_sync, record)

    async def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: SearchMode,
        document_id: str | None = None,
    ) -> list[RankedRetrievalHit]:
        if top_k < 1 or top_k > self._max_top_k:
            raise InvalidRetrievalParameterError(
                f"top_k must be between 1 and {self._max_top_k}"
            )
        if document_id:
            await self._document_service.get_document(document_id)
        return await asyncio.to_thread(
            self._search_sync,
            query,
            top_k,
            mode,
            document_id,
        )

    def _index_sync(self, record) -> IndexSummary:
        units = build_retrieval_units(record, self._dense.embedding)
        summary = self._dense.index_units(record, units)
        self._bm25.upsert_document(record, units)
        return summary

    def _search_sync(
        self,
        query: str,
        top_k: int,
        mode: SearchMode,
        document_id: str | None,
    ) -> list[RankedRetrievalHit]:
        if mode == SearchMode.DENSE:
            hits = self._dense.search_sync(query, top_k, document_id)
            return [
                RankedRetrievalHit(
                    rank=rank,
                    final_score=hit.score,
                    mode=mode.value,
                    unit=hit.to_unit(),
                    dense_rank=rank,
                    dense_score=hit.score,
                )
                for rank, hit in enumerate(hits, start=1)
            ]

        if mode == SearchMode.BM25:
            hits = self._bm25.search(
                query=query,
                top_k=top_k,
                document_id=document_id,
            )
            return [
                RankedRetrievalHit(
                    rank=rank,
                    final_score=hit.score,
                    mode=mode.value,
                    unit=hit.unit,
                    bm25_rank=rank,
                    bm25_score=hit.score,
                )
                for rank, hit in enumerate(hits, start=1)
            ]

        dense_hits = self._dense.search_sync(
            query,
            self._candidate_k,
            document_id,
        )
        if self._bm25.unit_count() == 0:
            raise IndexIncompatibleError(
                "BM25 index is empty. Re-index documents before hybrid search."
            )
        bm25_hits = self._bm25.search(
            query=query,
            top_k=self._candidate_k,
            document_id=document_id,
        )
        if document_id and not dense_hits and not bm25_hits:
            raise DocumentNotIndexedError(document_id)
        return reciprocal_rank_fusion(
            dense_hits=dense_hits,
            bm25_hits=bm25_hits,
            k=self._rrf_k,
            limit=top_k,
        )

