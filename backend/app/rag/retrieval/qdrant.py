"""Local persistent Qdrant vector storage."""

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.rag.exceptions import (
    DocumentNotIndexedError,
    IndexIncompatibleError,
    VectorStoreUnavailableError,
)
from app.rag.retrieval.types import SearchHit, VectorPoint

logger = logging.getLogger(__name__)


class QdrantVectorStore:
    """Own one local Qdrant client and one versioned collection."""

    def __init__(
        self,
        *,
        storage_dir: Path,
        model_name: str,
        dimension: int,
        index_version: int,
        query_instruction: str,
    ) -> None:
        self._storage_dir = storage_dir.resolve()
        self._model_name = model_name
        self._dimension = dimension
        self._index_version = index_version
        self._query_instruction = query_instruction
        self._manifest_path = (
            self._storage_dir.parent
            / f"{self._storage_dir.name}-index-manifest.json"
        )
        self._collection_name = self._build_collection_name()
        self._client: QdrantClient | None = None
        self._lock = threading.RLock()

    @property
    def collection_name(self) -> str:
        return self._collection_name

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        with self._lock:
            client = self._ensure_collection()
            batch_size = 64
            for start in range(0, len(points), batch_size):
                batch = points[start : start + batch_size]
                client.upsert(
                    collection_name=self._collection_name,
                    points=[
                        PointStruct(
                            id=point.point_id,
                            vector=point.vector,
                            payload=point.payload,
                        )
                        for point in batch
                    ],
                    wait=True,
                )

    def search(
        self,
        *,
        vector: list[float],
        top_k: int,
        document_id: str | None = None,
    ) -> list[SearchHit]:
        with self._lock:
            client = self._get_client()
            if not client.collection_exists(self._collection_name):
                raise DocumentNotIndexedError(document_id)
            self._validate_collection(client)

            query_filter = (
                Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                )
                if document_id
                else None
            )
            if document_id and self.count_document(document_id) == 0:
                raise DocumentNotIndexedError(document_id)

            result = client.query_points(
                collection_name=self._collection_name,
                query=vector,
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                with_vectors=False,
            )
            return [
                SearchHit(
                    score=float(point.score),
                    document_id=str(point.payload["document_id"]),
                    chunk_id=str(point.payload["chunk_id"]),
                    filename=str(point.payload["filename"]),
                    page_number=point.payload.get("page_number"),
                    chunk_index=int(point.payload["chunk_index"]),
                    content=str(point.payload["content"]),
                    part_index=int(point.payload["part_index"]),
                    part_count=int(point.payload["part_count"]),
                    original_chunk_char_count=int(
                        point.payload.get(
                            "original_chunk_char_count",
                            len(str(point.payload["content"])),
                        )
                    ),
                )
                for point in result.points
                if point.payload
            ]

    def count_document(self, document_id: str) -> int:
        with self._lock:
            client = self._get_client()
            if not client.collection_exists(self._collection_name):
                return 0
            count_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            )
            result = client.count(
                collection_name=self._collection_name,
                count_filter=count_filter,
                exact=True,
            )
            return int(result.count)

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _build_collection_name(self) -> str:
        safe_model = re.sub(
            r"[^a-z0-9_-]+",
            "-",
            self._model_name.lower(),
        ).strip("-_")
        digest = hashlib.sha256(
            (
                f"{self._model_name}:{self._dimension}:"
                f"{self._index_version}"
            ).encode("utf-8")
        ).hexdigest()[:8]
        return (
            f"opspilot_chunks_{safe_model[:32]}_"
            f"{self._dimension}_v{self._index_version}_{digest}"
        ).lower()

    def _get_client(self) -> QdrantClient:
        if self._client is not None:
            return self._client
        try:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(self._storage_dir))
            return self._client
        except Exception as exc:
            logger.error(
                "Could not open local Qdrant path=%s type=%s",
                self._storage_dir,
                type(exc).__name__,
            )
            raise VectorStoreUnavailableError(
                "Local Qdrant storage is unavailable or already open in another "
                "process. Run a single backend worker and close other instances."
            ) from exc

    def _ensure_collection(self) -> QdrantClient:
        client = self._get_client()
        if client.collection_exists(self._collection_name):
            self._validate_collection(client)
            self._ensure_manifest()
            return client

        client.create_collection(
            collection_name=self._collection_name,
            vectors_config=VectorParams(
                size=self._dimension,
                distance=Distance.COSINE,
            ),
        )
        self._write_manifest()
        return client

    def _validate_collection(self, client: QdrantClient) -> None:
        collection = client.get_collection(self._collection_name)
        vectors = collection.config.params.vectors
        actual_size = getattr(vectors, "size", None)
        if actual_size is None and isinstance(vectors, dict):
            first_vector = next(iter(vectors.values()), None)
            actual_size = getattr(first_vector, "size", None)
        if actual_size is not None and int(actual_size) != self._dimension:
            raise IndexIncompatibleError(
                f"Qdrant collection dimension {actual_size} does not match "
                f"embedding dimension {self._dimension}."
            )

        manifest = self._read_manifest()
        if manifest is None:
            self._write_manifest()
            return
        expected = {
            "embedding_model": self._model_name,
            "vector_dimension": self._dimension,
            "index_version": self._index_version,
            "query_instruction": self._query_instruction,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise IndexIncompatibleError(
                    "The existing vector index was created with different "
                    f"{key} settings. Re-index into a new version or model."
                )

    def _ensure_manifest(self) -> None:
        if self._read_manifest() is None:
            self._write_manifest()

    def _read_manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.is_file():
            return None
        try:
            return json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raise IndexIncompatibleError(
                "Vector index manifest is unreadable."
            )

    def _write_manifest(self) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._manifest_path.with_suffix(".json.tmp")
        payload = {
            "schema_version": 1,
            "collection_name": self._collection_name,
            "embedding_model": self._model_name,
            "vector_dimension": self._dimension,
            "index_version": self._index_version,
            "query_instruction": self._query_instruction,
            "distance": "COSINE",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self._manifest_path)

