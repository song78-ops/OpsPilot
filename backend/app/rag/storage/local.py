"""Filesystem-backed document metadata and original-file storage."""

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.rag.exceptions import (
    DocumentNotFoundError,
    DocumentStorageError,
)
from app.rag.types import DocumentChunk, DocumentRecord

logger = logging.getLogger(__name__)
_DOCUMENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_METADATA_FILENAME = "metadata.json"


class LocalDocumentStore:
    """Store each document in an isolated UUID directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save(self, record: DocumentRecord, source_path: Path) -> None:
        """Persist the source file and metadata, writing metadata last."""
        await asyncio.to_thread(self._save_sync, record, source_path)

    async def list_documents(self) -> list[DocumentRecord]:
        """Load valid records from disk, skipping incomplete directories."""
        return await asyncio.to_thread(self._list_sync)

    async def get_document(self, document_id: str) -> DocumentRecord:
        """Load one record by its validated UUID."""
        return await asyncio.to_thread(self._get_sync, document_id)

    def _save_sync(self, record: DocumentRecord, source_path: Path) -> None:
        target_dir = self._document_dir(record.document_id)
        metadata_path = target_dir / _METADATA_FILENAME
        target_file = target_dir / f"{record.document_id}{record.extension}"
        temporary_metadata = target_dir / f".{_METADATA_FILENAME}.tmp"

        try:
            self._root.mkdir(parents=True, exist_ok=True)
            target_dir.mkdir(parents=False, exist_ok=False)
            shutil.copyfile(source_path, target_file)
            temporary_metadata.write_text(
                json.dumps(
                    self._record_to_dict(record),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary_metadata, metadata_path)
        except Exception as exc:
            temporary_metadata.unlink(missing_ok=True)
            shutil.rmtree(target_dir, ignore_errors=True)
            logger.error(
                "Failed to persist document document_id=%s type=%s",
                record.document_id,
                type(exc).__name__,
            )
            raise DocumentStorageError() from exc

    def _list_sync(self) -> list[DocumentRecord]:
        if not self._root.exists():
            return []

        records: list[DocumentRecord] = []
        for entry in self._root.iterdir():
            if not entry.is_dir() or not _DOCUMENT_ID_PATTERN.fullmatch(entry.name):
                continue
            metadata_path = entry / _METADATA_FILENAME
            if not metadata_path.is_file():
                continue
            try:
                records.append(self._read_metadata(metadata_path))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                logger.warning(
                    "Skipping invalid document metadata document_id=%s",
                    entry.name,
                )

        records.sort(key=lambda record: record.uploaded_at, reverse=True)
        return records

    def _get_sync(self, document_id: str) -> DocumentRecord:
        target_dir = self._document_dir(document_id)
        metadata_path = target_dir / _METADATA_FILENAME
        if not metadata_path.is_file():
            raise DocumentNotFoundError(document_id)
        try:
            return self._read_metadata(metadata_path)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            logger.error(
                "Invalid stored metadata document_id=%s type=%s",
                document_id,
                type(exc).__name__,
            )
            raise DocumentStorageError(
                "Stored document metadata is unreadable."
            ) from exc

    def _document_dir(self, document_id: str) -> Path:
        if not _DOCUMENT_ID_PATTERN.fullmatch(document_id):
            raise DocumentNotFoundError(document_id)
        target = (self._root / document_id).resolve()
        if self._root not in target.parents:
            raise DocumentNotFoundError(document_id)
        return target

    @staticmethod
    def _record_to_dict(record: DocumentRecord) -> dict[str, Any]:
        return {
            "document_id": record.document_id,
            "filename": record.filename,
            "extension": record.extension,
            "content_type": record.content_type,
            "file_size": record.file_size,
            "content_sha256": record.content_sha256,
            "uploaded_at": record.uploaded_at.isoformat(),
            "chunk_size": record.chunk_size,
            "chunk_overlap": record.chunk_overlap,
            "chunks": [
                {
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "filename": chunk.filename,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                }
                for chunk in record.chunks
            ],
        }

    @staticmethod
    def _read_metadata(path: Path) -> DocumentRecord:
        data = json.loads(path.read_text(encoding="utf-8"))
        chunks = tuple(
            DocumentChunk(
                document_id=item["document_id"],
                chunk_id=item["chunk_id"],
                filename=item["filename"],
                page_number=item.get("page_number"),
                chunk_index=int(item["chunk_index"]),
                content=item["content"],
            )
            for item in data["chunks"]
        )
        return DocumentRecord(
            document_id=data["document_id"],
            filename=data["filename"],
            extension=data["extension"],
            content_type=data.get("content_type"),
            file_size=int(data["file_size"]),
            content_sha256=data["content_sha256"],
            uploaded_at=datetime.fromisoformat(data["uploaded_at"]),
            chunk_size=int(data["chunk_size"]),
            chunk_overlap=int(data["chunk_overlap"]),
            chunks=chunks,
        )

