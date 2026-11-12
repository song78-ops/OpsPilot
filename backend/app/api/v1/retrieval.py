"""Dense semantic retrieval endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_rerank_service, get_retrieval_service
from app.rag.retrieval.query import execute_retrieval
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.reranking.service import RerankService
from app.schemas.retrieval import (
    RetrievalHitResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post("/search", response_model=RetrievalSearchResponse)
async def search(
    payload: RetrievalSearchRequest,
    service: Annotated[HybridRetrievalService, Depends(get_retrieval_service)],
    rerank_service: Annotated[
        RerankService,
        Depends(get_rerank_service),
    ],
) -> RetrievalSearchResponse:
    """Return semantically similar indexed Chunk parts."""
    top_k = payload.top_k or service.default_top_k
    execution = await execute_retrieval(
        retrieval=service,
        rerank_service=rerank_service,
        query=payload.query,
        top_k=top_k,
        mode=payload.mode,
        rerank=payload.rerank,
        candidate_k=payload.candidate_k,
        document_id=payload.document_id,
    )
    model_info = service.model_info
    return RetrievalSearchResponse(
        query=payload.query,
        embedding_model=model_info.name,
        vector_dimension=model_info.dimension,
        index_version=service.index_version,
        top_k=top_k,
        mode=payload.mode,
        rrf_k=(
            service.rrf_k
            if payload.mode.value == "hybrid"
            else None
        ),
        rerank_requested=execution.rerank_requested,
        rerank_applied=execution.rerank_applied,
        rerank_model=execution.rerank_model,
        candidate_k=execution.candidate_k,
        items=[
            RetrievalHitResponse.from_domain(hit)
            for hit in execution.hits
        ],
    )

