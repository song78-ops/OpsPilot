"""Document upload and knowledge-base query response schemas."""

from datetime import datetime

from pydantic import BaseModel

from app.rag.types import DocumentChunk, DocumentRecord


class DocumentChunkResponse(BaseModel):
    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    char_count: int

    @classmethod
    def from_domain(cls, chunk: DocumentChunk) -> "DocumentChunkResponse":
        return cls(
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            filename=chunk.filename,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            char_count=chunk.char_count,
        )


class DocumentSummaryResponse(BaseModel):
    document_id: str
    filename: str
    extension: str
    content_type: str | None
    file_size: int
    content_sha256: str
    uploaded_at: datetime
    chunk_size: int
    chunk_overlap: int
    chunk_count: int

    @classmethod
    def from_domain(cls, record: DocumentRecord) -> "DocumentSummaryResponse":
        return cls(
            document_id=record.document_id,
            filename=record.filename,
            extension=record.extension,
            content_type=record.content_type,
            file_size=record.file_size,
            content_sha256=record.content_sha256,
            uploaded_at=record.uploaded_at,
            chunk_size=record.chunk_size,
            chunk_overlap=record.chunk_overlap,
            chunk_count=record.chunk_count,
        )


class DocumentDetailResponse(DocumentSummaryResponse):
    chunks: list[DocumentChunkResponse]

    @classmethod
    def from_domain(cls, record: DocumentRecord) -> "DocumentDetailResponse":
        summary = DocumentSummaryResponse.from_domain(record)
        return cls(
            **summary.model_dump(),
            chunks=[
                DocumentChunkResponse.from_domain(chunk)
                for chunk in record.chunks
            ],
        )


class DocumentListResponse(BaseModel):
    items: list[DocumentSummaryResponse]
    total: int

