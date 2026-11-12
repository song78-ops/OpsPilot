"""Reciprocal Rank Fusion for dense and lexical candidates."""

from app.rag.retrieval.types import (
    BM25Hit,
    RankedRetrievalHit,
    SearchHit,
)


def reciprocal_rank_fusion(
    *,
    dense_hits: list[SearchHit],
    bm25_hits: list[BM25Hit],
    k: int,
    limit: int,
) -> list[RankedRetrievalHit]:
    """Fuse ranked lists using rank-only RRF scores."""
    if k < 1:
        raise ValueError("RRF k must be positive")

    fused: dict[str, dict[str, object]] = {}
    for rank, hit in enumerate(dense_hits, start=1):
        state = fused.setdefault(
            hit.key,
            {
                "unit": hit.to_unit(),
                "dense_rank": None,
                "dense_score": None,
                "bm25_rank": None,
                "bm25_score": None,
                "rrf": 0.0,
            },
        )
        state["dense_rank"] = rank
        state["dense_score"] = hit.score
        state["rrf"] = float(state["rrf"]) + 1.0 / (k + rank)

    for rank, hit in enumerate(bm25_hits, start=1):
        state = fused.setdefault(
            hit.unit.key,
            {
                "unit": hit.unit,
                "dense_rank": None,
                "dense_score": None,
                "bm25_rank": None,
                "bm25_score": None,
                "rrf": 0.0,
            },
        )
        state["bm25_rank"] = rank
        state["bm25_score"] = hit.score
        state["rrf"] = float(state["rrf"]) + 1.0 / (k + rank)

    ordered = sorted(
        fused.values(),
        key=lambda item: (
            -float(item["rrf"]),
            int(item["dense_rank"] or 10_000),
            int(item["bm25_rank"] or 10_000),
            str(item["unit"].key),
        ),
    )
    return [
        RankedRetrievalHit(
            rank=rank,
            final_score=float(state["rrf"]),
            mode="hybrid",
            unit=state["unit"],
            dense_rank=state["dense_rank"],
            dense_score=state["dense_score"],
            bm25_rank=state["bm25_rank"],
            bm25_score=state["bm25_score"],
        )
        for rank, state in enumerate(ordered[:limit], start=1)
    ]

