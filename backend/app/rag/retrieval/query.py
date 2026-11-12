"""Shared retrieval execution used by search and RAG answer APIs."""

from dataclasses import dataclass

from app.rag.exceptions import InvalidRetrievalParameterError
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.retrieval.types import RankedRetrievalHit, SearchMode
from app.rag.reranking.service import RerankService


@dataclass(frozen=True, slots=True)
class RetrievalExecution:
    hits: list[RankedRetrievalHit]
    mode: SearchMode
    rerank_requested: bool
    rerank_applied: bool
    rerank_model: str | None
    candidate_k: int


async def execute_retrieval(
    *,
    retrieval: HybridRetrievalService,
    rerank_service: RerankService,
    query: str,
    top_k: int,
    mode: SearchMode,
    rerank: bool,
    candidate_k: int | None,
    document_id: str | None,
) -> RetrievalExecution:
    if rerank:
        effective_candidate_k = candidate_k or max(
            top_k,
            rerank_service.default_candidate_k,
        )
        if effective_candidate_k < top_k:
            raise InvalidRetrievalParameterError(
                "candidate_k must be greater than or equal to top_k."
            )
        if effective_candidate_k > retrieval.max_top_k:
            raise InvalidRetrievalParameterError(
                f"candidate_k must not exceed {retrieval.max_top_k}."
            )
        candidate_hits = await retrieval.search(
            query=query,
            top_k=effective_candidate_k,
            mode=mode,
            document_id=document_id,
        )
        hits, rerank_model = await rerank_service.rerank(
            query=query,
            hits=candidate_hits,
            top_k=top_k,
            candidate_k=effective_candidate_k,
        )
        return RetrievalExecution(
            hits=hits,
            mode=mode,
            rerank_requested=True,
            rerank_applied=True,
            rerank_model=rerank_model,
            candidate_k=effective_candidate_k,
        )

    hits = await retrieval.search(
        query=query,
        top_k=top_k,
        mode=mode,
        document_id=document_id,
    )
    return RetrievalExecution(
        hits=hits,
        mode=mode,
        rerank_requested=False,
        rerank_applied=False,
        rerank_model=None,
        candidate_k=top_k,
    )

