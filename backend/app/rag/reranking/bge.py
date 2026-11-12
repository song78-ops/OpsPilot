"""BGE CrossEncoder reranker for CPU inference."""

import logging
import threading
from pathlib import Path
from typing import Any

from app.rag.exceptions import (
    RerankerInputError,
    RerankerUnavailableError,
)
from app.rag.reranking.base import RerankerModelInfo, RerankScore

logger = logging.getLogger(__name__)


class BgeCrossEncoderReranker:
    """Lazily loaded CPU reranker shared by one application process."""

    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: Path,
        batch_size: int,
        max_length: int,
        overlap_tokens: int,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._max_length = max_length
        self._overlap_tokens = overlap_tokens
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def info(self) -> RerankerModelInfo:
        self._ensure_loaded()
        return RerankerModelInfo(
            name=self._model_name,
            max_length=self._max_length,
        )

    def score_pairs(
        self,
        query: str,
        documents: list[str],
    ) -> list[RerankScore]:
        if not documents:
            return []
        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        query_ids = self._token_ids(query)
        reserved_tokens = len(query_ids) + 4
        available = self._max_length - reserved_tokens
        if available < 16:
            raise RerankerInputError(
                "The query is too long to form a safe reranker input window."
            )

        pairs: list[tuple[str, str]] = []
        part_counts: list[int] = []
        for document in documents:
            document_ids = self._token_ids(document)
            parts = self._split_token_ids(document_ids, available)
            decoded_parts = [
                self._decode_tokens(part_ids).strip()
                for part_ids in parts
            ]
            decoded_parts = [part for part in decoded_parts if part]
            if not decoded_parts:
                decoded_parts = [document]
            part_counts.append(len(decoded_parts))
            pairs.extend((query, part) for part in decoded_parts)

        try:
            with self._inference_lock:
                predictions = self._model.predict(
                    pairs,
                    batch_size=self._batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
        except Exception as exc:
            logger.error(
                "Reranker inference failed model=%s type=%s",
                self._model_name,
                type(exc).__name__,
            )
            raise RerankerUnavailableError(
                "The reranker model failed during inference."
            ) from exc
        scores = (
            predictions.reshape(-1).tolist()
            if hasattr(predictions, "reshape")
            else list(predictions)
        )
        if len(scores) != len(pairs):
            raise RerankerUnavailableError(
                "The reranker returned an unexpected number of scores."
            )

        results: list[RerankScore] = []
        offset = 0
        for part_count in part_counts:
            candidate_scores = [
                float(score) for score in scores[offset : offset + part_count]
            ]
            offset += part_count
            results.append(
                RerankScore(
                    score=max(candidate_scores),
                    inferred_part_count=part_count,
                )
            )
        return results

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                from sentence_transformers import CrossEncoder

                self._cache_dir.mkdir(parents=True, exist_ok=True)
                local_model_dir = self._cache_dir / self._model_name.replace(
                    "/",
                    "--",
                )
                if (local_model_dir / "config.json").is_file():
                    model = CrossEncoder(
                        str(local_model_dir),
                        device="cpu",
                        max_length=self._max_length,
                    )
                else:
                    model = CrossEncoder(
                        self._model_name,
                        device="cpu",
                        max_length=self._max_length,
                        cache_folder=str(self._cache_dir),
                    )
                self._model = model
                self._tokenizer = model.tokenizer
            except Exception as exc:
                logger.error(
                    "Reranker load failed model=%s type=%s",
                    self._model_name,
                    type(exc).__name__,
                )
                raise RerankerUnavailableError(
                    f"Could not load reranker model '{self._model_name}' on CPU."
                ) from exc

    def _token_ids(self, text: str) -> list[int]:
        assert self._tokenizer is not None
        backend = getattr(self._tokenizer, "backend_tokenizer", None)
        if backend is not None:
            backend.no_truncation()
            return list(
                backend.encode(text, add_special_tokens=False).ids
            )
        return list(self._tokenizer.encode(text, add_special_tokens=False))

    def _decode_tokens(self, token_ids: list[int]) -> str:
        assert self._tokenizer is not None
        return self._tokenizer.decode(token_ids, skip_special_tokens=True)

    def _split_token_ids(
        self,
        token_ids: list[int],
        available: int,
    ) -> list[list[int]]:
        if len(token_ids) <= available:
            return [token_ids]
        step = max(1, available - self._overlap_tokens)
        return [
            token_ids[start : start + available]
            for start in range(0, len(token_ids), step)
            if token_ids[start : start + available]
        ]

