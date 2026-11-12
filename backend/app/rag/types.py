"""Provider-independent document parsing and chunking data types."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ParsedSection:
    """Text extracted from one page or one logical document section."""

    text: str
    page_number: int | None = None


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """One chunk ready for later embedding and retrieval."""

    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    content: str

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Persistent document metadata and generated chunks."""

    document_id: str
    filename: str
    extension: str
    content_type: str | None
    file_size: int
    content_sha256: str
    uploaded_at: datetime
    chunk_size: int
    chunk_overlap: int
    chunks: tuple[DocumentChunk, ...]

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)

