"""Opt-in real CrossEncoder reranker integration test."""

import os

import pytest

from app.core.config import get_settings
from app.rag.reranking.bge import BgeCrossEncoderReranker


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_RERANKER_TESTS") != "1",
    reason="Set RUN_REAL_RERANKER_TESTS=1 to load the real BGE reranker",
)


def test_real_reranker_cpu_batch_and_safe_long_text() -> None:
    settings = get_settings()
    reranker = BgeCrossEncoderReranker(
        model_name=settings.reranker_model_name,
        cache_dir=settings.resolved_model_cache_dir,
        batch_size=4,
        max_length=settings.reranker_max_length,
        overlap_tokens=settings.reranker_overlap_tokens,
    )
    long_document = "Redis 缓存过期与重建说明。" * 300

    scores = reranker.score_pairs(
        "缓存击穿应该如何重建",
        [
            "Redis 缓存击穿可以使用互斥锁和逻辑过期。",
            "MySQL 使用事务保存订单。",
            long_document,
        ],
    )

    assert reranker.info.name == "BAAI/bge-reranker-base"
    assert len(scores) == 3
    assert scores[0].score > scores[1].score
    assert scores[2].inferred_part_count > 1

