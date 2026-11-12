"""Knowledge-base document upload and inspection endpoints."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import get_document_service, get_retrieval_service
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.service import DocumentService
from app.schemas.document import (
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentSummaryResponse,
)
from app.schemas.retrieval import DocumentIndexResponse

router = APIRouter(prefix="/documents", tags=["documents"])


async def upload_chunks(file: UploadFile) -> AsyncIterator[bytes]:
    """Yield uploaded bytes without loading the full document into memory."""
    while chunk := await file.read(1024 * 1024):
        yield chunk


@router.post(
    "/upload",
    response_model=DocumentDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    service: Annotated[DocumentService, Depends(get_document_service)],
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT, or Markdown")],
) -> DocumentDetailResponse:
    """Parse an uploaded document, chunk it, and persist both files and metadata."""
    record = await service.ingest(
        filename=file.filename,
        content_type=file.content_type,
        content=upload_chunks(file),
    )
    return DocumentDetailResponse.from_domain(record)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentListResponse:
    """List persisted knowledge-base documents without exposing file paths."""
    records = await service.list_documents()
    return DocumentListResponse(
        items=[DocumentSummaryResponse.from_domain(record) for record in records],
        total=len(records),
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> DocumentDetailResponse:
    """Return one document with all generated chunks."""
    record = await service.get_document(document_id)
    return DocumentDetailResponse.from_domain(record)


@router.post(
    "/{document_id}/index",
    response_model=DocumentIndexResponse,
)
async def index_document(
    document_id: str,
    service: Annotated[
        HybridRetrievalService,
        Depends(get_retrieval_service),
    ],
) -> DocumentIndexResponse:
    """Generate and persist dense vectors for all document chunks."""
    summary = await service.index_document(document_id)
    return DocumentIndexResponse.from_domain(summary)

