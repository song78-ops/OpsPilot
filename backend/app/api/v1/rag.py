"""Knowledge-base grounded answer endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_rag_qa_service
from app.rag.qa.service import RagQAService
from app.schemas.rag import RagAskRequest, RagAskResponse

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/ask", response_model=RagAskResponse)
async def ask(
    payload: RagAskRequest,
    service: Annotated[RagQAService, Depends(get_rag_qa_service)],
) -> RagAskResponse:
    """Answer from knowledge-base evidence and return validated citations."""
    return await service.ask(
        query=payload.query,
        top_k=payload.top_k,
        mode=payload.mode,
        rerank=payload.rerank,
        candidate_k=payload.candidate_k,
        document_id=payload.document_id,
    )

