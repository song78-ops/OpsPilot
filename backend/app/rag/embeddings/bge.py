"""SentenceTransformers-backed BGE embedding adapter."""

import threading
from pathlib import Path
from typing import Any

from app.rag.embeddings.base import EmbeddingModelInfo
from app.rag.exceptions import (
    EmbeddingDimensionError,
    EmbeddingUnavailableError,
    QueryTokenLimitError,
)


class BgeEmbeddingModel:
    """Lazy CPU-only BGE model loaded once per application process."""

    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: Path,
        batch_size: int,
        max_tokens: int,
        overlap_tokens: int,
        query_instruction: str,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._max_tokens = max_tokens
        self._overlap_tokens = overlap_tokens
        self._query_instruction = query_instruction
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._dimension: int | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def info(self) -> EmbeddingModelInfo:
        self._ensure_loaded()
        assert self._dimension is not None
        return EmbeddingModelInfo(
            name=self._model_name,
            dimension=self._dimension,
            max_tokens=self._max_tokens,
            query_instruction=self._query_instruction,
        )

    def count_tokens(self, text: str) -> int:
        self._ensure_loaded()
        assert self._tokenizer is not None
        backend = getattr(self._tokenizer, "backend_tokenizer", None)
        if backend is not None:
            backend.no_truncation()
            return len(
                backend.encode(text, add_special_tokens=True).ids
            )
        return len(self._tokenizer.encode(text, add_special_tokens=True))

    def split_text(self, text: str) -> list[str]:
        """Split by tokenizer windows while preserving every token segment."""
        if self.count_tokens(text) <= self._max_tokens:
            return [text]

        assert self._tokenizer is not None
        backend = getattr(self._tokenizer, "backend_tokenizer", None)
        if backend is not None:
            backend.no_truncation()
            token_ids = backend.encode(
                text,
                add_special_tokens=False,
            ).ids
        else:
            token_ids = self._tokenizer.encode(
                text,
                add_special_tokens=False,
            )
        available_tokens = max(1, self._max_tokens - 2)
        step = max(1, available_tokens - self._overlap_tokens)
        pieces: list[str] = []

        for start in range(0, len(token_ids), step):
            part_ids = token_ids[start : start + available_tokens]
            if not part_ids:
                break
            piece = self._tokenizer.decode(
                part_ids,
                skip_special_tokens=True,
            ).strip()
            if piece:
                pieces.append(piece)
            if start + available_tokens >= len(token_ids):
                break

        if not pieces:
            raise EmbeddingUnavailableError(
                "The embedding tokenizer could not split the input safely."
            )
        return pieces

    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(self.count_tokens(text) > self._max_tokens for text in texts):
            raise ValueError("All document texts must be split before encoding")

        self._ensure_loaded()
        assert self._model is not None
        with self._inference_lock:
            vectors = self._model.encode(
                texts,
                batch_size=self._batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        result = vectors.tolist() if hasattr(vectors, "tolist") else vectors
        self._validate_vectors(result)
        return result

    def encode_query(self, query: str) -> list[float]:
        instructed_query = f"{self._query_instruction}{query}"
        token_count = self.count_tokens(instructed_query)
        if token_count > self._max_tokens:
            raise QueryTokenLimitError(token_count, self._max_tokens)

        vectors = self.encode_documents([instructed_query])
        return vectors[0]

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer

                self._cache_dir.mkdir(parents=True, exist_ok=True)
                local_model_dir = self._cache_dir / self._model_name.replace(
                    "/",
                    "--",
                )
                if (local_model_dir / "config.json").is_file():
                    model = SentenceTransformer(
                        str(local_model_dir),
                        device="cpu",
                    )
                else:
                    model = SentenceTransformer(
                        self._model_name,
                        device="cpu",
                        cache_folder=str(self._cache_dir),
                    )
                model.max_seq_length = self._max_tokens
                get_dimension = getattr(
                    model,
                    "get_embedding_dimension",
                    None,
                ) or getattr(model, "get_sentence_embedding_dimension")
                dimension = get_dimension()
                if not dimension:
                    raise ValueError("Model did not report an embedding dimension")
                self._model = model
                self._tokenizer = model.tokenizer
                self._dimension = int(dimension)
            except Exception as exc:
                raise EmbeddingUnavailableError(
                    f"Could not load embedding model '{self._model_name}' on CPU."
                ) from exc

    def _validate_vectors(self, vectors: list[list[float]]) -> None:
        if self._dimension is None:
            raise EmbeddingUnavailableError("Embedding model is not loaded.")
        for vector in vectors:
            if len(vector) != self._dimension:
                raise EmbeddingDimensionError(self._dimension, len(vector))

