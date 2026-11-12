"""Persistent lexical BM25 index built from the shared retrieval units."""

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Plus

from app.rag.exceptions import (
    DocumentNotIndexedError,
    IndexIncompatibleError,
)
from app.rag.retrieval.tokenizer import BM25Tokenizer
from app.rag.retrieval.types import BM25Hit, RetrievalUnit
from app.rag.types import DocumentRecord


class BM25IndexStore:
    """Persist tokenized units and rebuild the BM25 matrix on load."""

    def __init__(
        self,
        *,
        storage_dir: Path,
        embedding_model: str,
        index_version: int,
        k1: float,
        b: float,
    ) -> None:
        self._storage_dir = storage_dir.resolve()
        self._embedding_model = embedding_model
        self._index_version = index_version
        self._k1 = k1
        self._b = b
        self._tokenizer = BM25Tokenizer()
        self._index_path = self._build_index_path()
        self._lock = threading.RLock()
        self._documents: dict[str, dict[str, Any]] = {}
        self._units: list[RetrievalUnit] = []
        self._matrix: BM25Plus | None = None
        self._loaded = False

    @property
    def index_path(self) -> Path:
        return self._index_path

    def upsert_document(
        self,
        record: DocumentRecord,
        units: list[RetrievalUnit],
    ) -> None:
        with self._lock:
            self._ensure_loaded()
            self._documents[record.document_id] = {
                "content_sha256": record.content_sha256,
                "chunk_size": record.chunk_size,
                "chunk_overlap": record.chunk_overlap,
                "units": [
                    {
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
                        "tokens": self._tokenizer.tokenize(unit.content),
                    }
                    for unit in units
                ],
            }
            self._persist()
            self._rebuild()

    def search(
        self,
        *,
        query: str,
        top_k: int,
        document_id: str | None = None,
    ) -> list[BM25Hit]:
        with self._lock:
            self._ensure_loaded()
            if self._matrix is None or not self._units:
                raise DocumentNotIndexedError(document_id)
            if document_id and document_id not in self._documents:
                raise DocumentNotIndexedError(document_id)

            query_tokens = self._tokenizer.tokenize(query)
            if not query_tokens:
                return []

            scores = self._matrix.get_scores(query_tokens)
            ranked = [
                (float(score), unit)
                for score, unit in zip(scores, self._units, strict=True)
                if score > 0
                and (document_id is None or unit.document_id == document_id)
            ]
            ranked.sort(key=lambda item: (-item[0], item[1].key))
            return [
                BM25Hit(score=score, unit=unit)
                for score, unit in ranked[:top_k]
            ]

    def count_document_units(self, document_id: str) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._documents.get(document_id, {}).get("units", []))

    def unit_count(self) -> int:
        with self._lock:
            self._ensure_loaded()
            return len(self._units)

    def _build_index_path(self) -> Path:
        digest = hashlib.sha256(
            (
                f"{self._embedding_model}:{self._index_version}:"
                f"{self._tokenizer.version}:{self._k1}:{self._b}"
            ).encode("utf-8")
        ).hexdigest()[:10]
        safe_model = re.sub(
            r"[^a-z0-9_-]+",
            "-",
            self._embedding_model.lower(),
        ).strip("-_")[:32]
        return (
            self._storage_dir
            / f"bm25-{safe_model}-v{self._index_version}-{digest}.json"
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._index_path.is_file():
            return
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
            self._validate_manifest(payload)
            self._documents = payload["documents"]
            self._rebuild()
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise IndexIncompatibleError(
                "The BM25 index is unreadable or incompatible. Re-index documents."
            ) from exc

    def _validate_manifest(self, payload: dict[str, Any]) -> None:
        expected = {
            "schema_version": 1,
            "embedding_model": self._embedding_model,
            "index_version": self._index_version,
            "tokenizer_version": self._tokenizer.version,
            "k1": self._k1,
            "b": self._b,
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                raise IndexIncompatibleError(
                    f"BM25 index has incompatible {key}."
                )

    def _persist(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._index_path.with_suffix(".json.tmp")
        payload = {
            "schema_version": 1,
            "embedding_model": self._embedding_model,
            "index_version": self._index_version,
            "tokenizer_version": self._tokenizer.version,
            "k1": self._k1,
            "b": self._b,
            "documents": self._documents,
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temporary, self._index_path)

    def _rebuild(self) -> None:
        self._units = []
        corpus: list[list[str]] = []
        for document_id in sorted(self._documents):
            for item in self._documents[document_id]["units"]:
                self._units.append(
                    RetrievalUnit(
                        document_id=item["document_id"],
                        chunk_id=item["chunk_id"],
                        filename=item["filename"],
                        page_number=item.get("page_number"),
                        chunk_index=int(item["chunk_index"]),
                        content=item["content"],
                        part_index=int(item["part_index"]),
                        part_count=int(item["part_count"]),
                        original_chunk_char_count=int(
                            item["original_chunk_char_count"]
                        ),
                    )
                )
                corpus.append(item["tokens"])

        self._matrix = (
            BM25Plus(corpus, k1=self._k1, b=self._b)
            if corpus
            else None
        )

