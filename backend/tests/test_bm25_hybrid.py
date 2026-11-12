"""BM25 tokenization, RRF, and hybrid retrieval tests."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_retrieval_service
from app.main import app
from app.rag.exceptions import DocumentNotIndexedError, IndexIncompatibleError
from app.rag.retrieval.qdrant import QdrantVectorStore
from app.rag.retrieval.rrf import reciprocal_rank_fusion
from app.rag.retrieval.tokenizer import BM25Tokenizer
from app.rag.retrieval.types import (
    BM25Hit,
    RetrievalUnit,
    SearchHit,
    SearchMode,
)
from tests.fakes import FakeEmbeddingModel
from tests.test_retrieval import (
    build_hybrid_services,
    build_services,
    ingest_text,
)


def unit(
    *,
    document_id: str,
    chunk_id: str,
    content: str,
    part_index: int = 1,
) -> RetrievalUnit:
    return RetrievalUnit(
        document_id=document_id,
        chunk_id=chunk_id,
        filename=f"{document_id}.txt",
        page_number=None,
        chunk_index=1,
        content=content,
        part_index=part_index,
        part_count=1,
        original_chunk_char_count=len(content),
    )


def test_mixed_tokenizer_preserves_codes_and_chinese() -> None:
    tokenizer = BM25Tokenizer()

    tokens = tokenizer.tokenize(
        "Redis 缓存击穿，错误代码 CACHE_ERR_504，版本 v2.3.1"
    )

    assert "redis" in tokens
    assert "缓存" in tokens
    assert "击穿" in tokens
    assert "cache_err_504" in tokens
    assert "v2.3.1" in tokens
    assert "504" in tokens


def test_rrf_uses_rank_only_and_deduplicates_candidates() -> None:
    shared = unit(
        document_id="a" * 32,
        chunk_id=f"{'a' * 32}:0001",
        content="shared",
    )
    dense_only = unit(
        document_id="b" * 32,
        chunk_id=f"{'b' * 32}:0001",
        content="dense",
    )
    bm25_only = unit(
        document_id="c" * 32,
        chunk_id=f"{'c' * 32}:0001",
        content="bm25",
    )
    dense_hits = [
        SearchHit(
            score=0.9,
            document_id=shared.document_id,
            chunk_id=shared.chunk_id,
            filename=shared.filename,
            page_number=None,
            chunk_index=1,
            content=shared.content,
            part_index=1,
            part_count=1,
            original_chunk_char_count=len(shared.content),
        ),
        SearchHit(
            score=0.8,
            document_id=dense_only.document_id,
            chunk_id=dense_only.chunk_id,
            filename=dense_only.filename,
            page_number=None,
            chunk_index=1,
            content=dense_only.content,
            part_index=1,
            part_count=1,
            original_chunk_char_count=len(dense_only.content),
        ),
    ]
    lexical_hits = [
        BM25Hit(score=12.0, unit=bm25_only),
        BM25Hit(score=10.0, unit=shared),
    ]

    fused = reciprocal_rank_fusion(
        dense_hits=dense_hits,
        bm25_hits=lexical_hits,
        k=60,
        limit=3,
    )

    assert len(fused) == 3
    assert fused[0].unit.key == shared.key
    assert fused[0].final_score == pytest.approx(1 / 61 + 1 / 62)
    assert fused[0].dense_rank == 1
    assert fused[0].bm25_rank == 2
    assert fused[1].final_score == pytest.approx(1 / 61)
    assert fused[2].final_score == pytest.approx(1 / 62)


async def test_dense_bm25_hybrid_modes_and_document_filter(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, bm25_store = build_hybrid_services(
        tmp_path
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    try:
        redis_doc = await ingest_text(
            document_service,
            filename="redis.txt",
            text="Redis 缓存击穿使用互斥锁，错误代码 CACHE_ERR_504。",
        )
        mysql_doc = await ingest_text(
            document_service,
            filename="mysql.txt",
            text="MySQL 订单事务保证库存一致性。",
        )
        for record in (redis_doc, mysql_doc):
            await retrieval.index_document(record.document_id)

        dense = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存击穿", "top_k": 2},
        )
        lexical = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "CACHE_ERR_504",
                "top_k": 2,
                "mode": "bm25",
            },
        )
        hybrid = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存失效错误代码",
                "top_k": 2,
                "mode": "hybrid",
            },
        )
        filtered = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "事务",
                "top_k": 2,
                "mode": "hybrid",
                "document_id": mysql_doc.document_id,
            },
        )
        invalid_mode = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存", "mode": "invalid"},
        )

        assert dense.status_code == 200
        assert dense.json()["mode"] == "dense"
        assert dense.json()["items"][0]["dense_rank"] == 1
        assert dense.json()["items"][0]["bm25_rank"] is None

        assert lexical.status_code == 200
        assert lexical.json()["mode"] == "bm25"
        assert lexical.json()["items"][0]["filename"] == "redis.txt"
        assert lexical.json()["items"][0]["bm25_rank"] == 1
        assert lexical.json()["items"][0]["dense_rank"] is None

        assert hybrid.status_code == 200
        assert hybrid.json()["mode"] == "hybrid"
        assert hybrid.json()["rrf_k"] == 60
        assert hybrid.json()["items"][0]["filename"] == "redis.txt"
        assert hybrid.json()["items"][0]["score"] > 0
        assert filtered.status_code == 200
        assert all(
            item["document_id"] == mysql_doc.document_id
            for item in filtered.json()["items"]
        )
        assert invalid_mode.status_code == 422
        assert bm25_store.count_document_units(redis_doc.document_id) == 1
    finally:
        store.close()


async def test_repeated_hybrid_index_has_no_duplicate_units(
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, bm25_store = build_hybrid_services(
        tmp_path
    )
    try:
        record = await ingest_text(
            document_service,
            filename="repeat.txt",
            text="Redis 缓存需要过期时间。",
        )
        await retrieval.index_document(record.document_id)
        await retrieval.index_document(record.document_id)

        assert bm25_store.count_document_units(record.document_id) == 1
        hits = bm25_store.search(query="Redis", top_k=10)
        assert len({hit.unit.key for hit in hits}) == len(hits)
    finally:
        store.close()


async def test_bm25_index_survives_restart(tmp_path: Path) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    record = await ingest_text(
        document_service,
        filename="persist-bm25.txt",
        text="产品或编号 QDRANT_LOCK_409 表示本地目录被锁定。",
    )
    await retrieval.index_document(record.document_id)
    store.close()

    _, restarted, restarted_store, _ = build_hybrid_services(tmp_path)
    try:
        hits = await restarted.search(
            query="QDRANT_LOCK_409",
            top_k=3,
            mode=SearchMode.BM25,
        )
        assert hits[0].unit.document_id == record.document_id
    finally:
        restarted_store.close()


async def test_bm25_upsert_replaces_stale_document_content(
    tmp_path: Path,
) -> None:
    embedding = FakeEmbeddingModel()
    document_service, dense, store = build_services(
        tmp_path,
        embedding=embedding,
    )
    _ = document_service
    from app.rag.retrieval.bm25 import BM25IndexStore

    lexical = BM25IndexStore(
        storage_dir=tmp_path / "bm25",
        embedding_model=embedding.info.name,
        index_version=1,
        k1=1.5,
        b=0.75,
    )
    document_id = "a" * 32
    try:
        record = await ingest_text(
            document_service,
            filename="replace.txt",
            text="旧内容 Redis 缓存。",
        )
        old_unit = unit(
            document_id=document_id,
            chunk_id=f"{document_id}:0001",
            content="旧内容 Redis 缓存。",
        )
        lexical.upsert_document(record, [old_unit])

        updated_record = replace(record, content_sha256="updated")
        new_unit = unit(
            document_id=document_id,
            chunk_id=f"{document_id}:0001",
            content="新内容 MySQL 事务。",
        )
        lexical.upsert_document(updated_record, [new_unit])

        assert lexical.search(query="Redis", top_k=5) == []
        hits = lexical.search(query="MySQL", top_k=5)
        assert len(hits) == 1
        assert hits[0].unit.content == "新内容 MySQL 事务。"
    finally:
        store.close()


async def test_empty_and_inconsistent_indexes_are_explicit(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, dense, store = build_services(tmp_path)
    from app.rag.retrieval.bm25 import BM25IndexStore
    from app.rag.retrieval.hybrid import HybridRetrievalService

    empty_bm25 = BM25IndexStore(
        storage_dir=tmp_path / "bm25",
        embedding_model=dense.model_info.name,
        index_version=1,
        k1=1.5,
        b=0.75,
    )
    hybrid = HybridRetrievalService(
        document_service=document_service,
        dense=dense,
        bm25=empty_bm25,
        rrf_k=60,
        candidate_k=20,
        max_top_k=20,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: hybrid
    try:
        empty = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "Redis", "mode": "bm25"},
        )
        record = await ingest_text(
            document_service,
            filename="dense-only.txt",
            text="Redis 缓存。",
        )
        await dense.index_document(record.document_id)
        inconsistent = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "Redis", "mode": "hybrid"},
        )

        assert empty.status_code == 409
        assert empty.json()["error"]["code"] == "DOCUMENT_NOT_INDEXED"
        assert inconsistent.status_code == 409
        assert inconsistent.json()["error"]["code"] == "INDEX_INCOMPATIBLE"
    finally:
        store.close()

