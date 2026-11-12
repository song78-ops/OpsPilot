"""Apply CrossEncoder scores to existing ranked retrieval candidates."""

import asyncio
from dataclasses import replace

from app.rag.exceptions import (
    InvalidRetrievalParameterError,
    RerankerInputError,
    RerankerUnavailableError,
)
from app.rag.reranking.base import RerankerProvider
from app.rag.retrieval.types import RankedRetrievalHit


class RerankService:
    """Rerank candidates while retaining original retrieval provenance."""

    def __init__(
        self,
        *,
        reranker: RerankerProvider | None,
        default_candidate_k: int,
        max_top_k: int,
    ) -> None:
        self._reranker = reranker
        self._default_candidate_k = default_candidate_k
        self._max_top_k = max_top_k

    @property
    def default_candidate_k(self) -> int:
        return self._default_candidate_k

    async def rerank(
        self,
        *,
        query: str,
        hits: list[RankedRetrievalHit],
        top_k: int,
        candidate_k: int | None,
    ) -> tuple[list[RankedRetrievalHit], str]:
        reranker = self._reranker
        if reranker is None:
            raise RerankerUnavailableError(
                "Reranking is disabled or the reranker dependency is unresolved."
            )
        effective_candidate_k = candidate_k or self._default_candidate_k
        if effective_candidate_k < top_k:
            raise InvalidRetrievalParameterError(
                "candidate_k must be greater than or equal to top_k."
            )
        if effective_candidate_k > self._max_top_k:
            raise InvalidRetrievalParameterError(
                f"candidate_k must not exceed {self._max_top_k}."
            )
        if len(hits) < top_k:
            raise RerankerInputError(
                "Fewer retrieval candidates were available than requested top_k."
            )

        scores = await asyncio.to_thread(
            reranker.score_pairs,
            query,
            [hit.unit.content for hit in hits],
        )
        if len(scores) != len(hits):
            raise RerankerUnavailableError(
                "The reranker returned incomplete candidate scores."
            )

        ordered = sorted(
            zip(hits, scores, strict=True),
            key=lambda item: (-item[1].score, item[0].rank),
        )
        reranked = [
            replace(
                hit,
                rank=rank,
                final_score=score.score,
                retrieval_rank=hit.rank,
                retrieval_score=hit.final_score,
                rerank_score=score.score,
            )
            for rank, (hit, score) in enumerate(
                ordered[:top_k],
                start=1,
            )
        ]
        model_name = await asyncio.to_thread(lambda: reranker.info.name)
        return reranked, model_name

