"""Document upload orchestration for parse, clean, chunk, and persistence."""

import asyncio
import hashlib
import logging
import re
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from app.core.exceptions import ApplicationError
from app.rag.chunking.paragraph import ParagraphChunker
from app.rag.exceptions import (
    DocumentParseError,
    DocumentTooLargeError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from app.rag.parsing.cleaner import clean_text
from app.rag.parsing.factory import SUPPORTED_EXTENSIONS, parse_document
from app.rag.storage.local import LocalDocumentStore
from app.rag.types import DocumentRecord, ParsedSection

logger = logging.getLogger(__name__)
_CONTROL_FILENAME_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def safe_filename(filename: str | None) -> str:
    """Strip directory components and unsafe control characters."""
    if not filename:
        raise DocumentValidationError("The uploaded file must have a filename.")

    normalized = filename.replace("\\", "/")
    base = PurePosixPath(normalized).name
    base = _CONTROL_FILENAME_CHARS.sub("", base).strip()
    if base in {"", ".", ".."}:
        raise DocumentValidationError("The uploaded filename is invalid.")
    if len(base) > 255:
        raise DocumentValidationError("The uploaded filename is too long.")
    return base


class DocumentService:
    """Validate an upload and run the document ingestion pipeline."""

    def __init__(
        self,
        *,
        store: LocalDocumentStore,
        max_upload_bytes: int,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        self._store = store
        self._max_upload_bytes = max_upload_bytes
        self._chunker = ParagraphChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        content: AsyncIterator[bytes],
    ) -> DocumentRecord:
        """Save, parse, clean, and chunk one uploaded document."""
        original_filename = safe_filename(filename)
        extension = PurePosixPath(original_filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise UnsupportedDocumentTypeError(extension)

        temp_path = None
        temp_file = None
        try:
            temp_file = tempfile.NamedTemporaryFile(
                prefix="opspilot-upload-",
                suffix=extension,
                delete=False,
            )
            temp_path = temp_file.name
            file_size = 0
            digest = hashlib.sha256()

            async for chunk in content:
                if not chunk:
                    continue
                file_size += len(chunk)
                if file_size > self._max_upload_bytes:
                    raise DocumentTooLargeError(self._max_upload_bytes)
                digest.update(chunk)
                temp_file.write(chunk)
            temp_file.close()

            if file_size == 0:
                raise DocumentValidationError("The uploaded document is empty.")

            path = Path(temp_path)
            try:
                parsed_sections = await asyncio.to_thread(
                    parse_document,
                    path,
                    extension,
                )
            except ApplicationError:
                raise
            except Exception as exc:
                logger.warning(
                    "Document parsing failed extension=%s type=%s",
                    extension,
                    type(exc).__name__,
                )
                raise DocumentParseError(
                    "The document is damaged or its text could not be extracted."
                ) from exc
            cleaned_sections = [
                ParsedSection(
                    text=clean_text(section.text),
                    page_number=section.page_number,
                )
                for section in parsed_sections
            ]
            cleaned_sections = [
                section for section in cleaned_sections if section.text
            ]
            if not cleaned_sections:
                raise DocumentParseError(
                    "The document contains no usable text after cleaning."
                )

            document_id = uuid.uuid4().hex
            chunks = await asyncio.to_thread(
                self._chunker.chunk,
                document_id=document_id,
                filename=original_filename,
                sections=cleaned_sections,
            )
            if not chunks:
                raise DocumentParseError(
                    "The document could not be split into usable chunks."
                )

            record = DocumentRecord(
                document_id=document_id,
                filename=original_filename,
                extension=extension,
                content_type=(content_type or "")[:255] or None,
                file_size=file_size,
                content_sha256=digest.hexdigest(),
                uploaded_at=datetime.now(timezone.utc),
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
                chunks=tuple(chunks),
            )
            await self._store.save(record, path)
            logger.info(
                "Document ingested document_id=%s chunks=%d",
                document_id,
                len(chunks),
            )
            return record
        finally:
            if temp_file is not None and not temp_file.closed:
                temp_file.close()
            if temp_path is not None:
                await asyncio.to_thread(Path(temp_path).unlink, missing_ok=True)

    async def list_documents(self) -> list[DocumentRecord]:
        return await self._store.list_documents()

    async def get_document(self, document_id: str) -> DocumentRecord:
        return await self._store.get_document(document_id)

