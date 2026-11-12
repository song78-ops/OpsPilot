"""Opt-in integration test using the real BGE model on CPU."""

import os

import pytest

from app.core.config import get_settings
from app.rag.embeddings.bge import BgeEmbeddingModel


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REAL_EMBEDDING_TESTS") != "1",
    reason="Set RUN_REAL_EMBEDDING_TESTS=1 to load the real BGE model",
)


def test_real_bge_cpu_embedding_and_token_split() -> None:
    settings = get_settings()
    model = BgeEmbeddingModel(
        model_name=settings.embedding_model_name,
        cache_dir=settings.resolved_model_cache_dir,
        batch_size=settings.embedding_batch_size,
        max_tokens=settings.embedding_max_tokens,
        overlap_tokens=settings.embedding_overlap_tokens,
        query_instruction=settings.embedding_query_instruction,
    )

    document_vector = model.encode_documents(["Redis 用于缓存热点数据。"])[0]
    query_vector = model.encode_query("缓存失效如何处理")
    long_text = "企业知识库文档内容。" * 200
    parts = model.split_text(long_text)

    assert model.info.dimension == 512
    assert len(document_vector) == 512
    assert len(query_vector) == 512
    assert model.count_tokens(long_text) > settings.embedding_max_tokens
    assert len(parts) > 1
    assert all(model.count_tokens(part) <= 512 for part in parts)

