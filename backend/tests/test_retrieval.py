"""Offline dense indexing and Qdrant Local retrieval tests."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_retrieval_service
from app.main import app
from app.rag.exceptions import (
    DocumentNotIndexedError,
    EmbeddingDimensionError,
)
from app.rag.retrieval.qdrant import QdrantVectorStore
from app.rag.retrieval.bm25 import BM25IndexStore
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.retrieval.service import DenseRetrievalService
from app.rag.service import DocumentService
from app.rag.storage.local import LocalDocumentStore
from tests.fakes import FakeEmbeddingModel


async def ingest_text(
    service: DocumentService,
    *,
    filename: str,
    text: str,
):
    async def content() -> AsyncIterator[bytes]:
        yield text.encode("utf-8")

    return await service.ingest(
        filename=filename,
        content_type="text/plain",
        content=content(),
    )


def build_services(
    root: Path,
    *,
    embedding: FakeEmbeddingModel | None = None,
):
    embedding = embedding or FakeEmbeddingModel()
    document_service = DocumentService(
        store=LocalDocumentStore(root / "documents"),
        max_upload_bytes=100_000,
        chunk_size=400,
        chunk_overlap=30,
    )
    model_info = embedding.info
    vector_store = QdrantVectorStore(
        storage_dir=root / "qdrant",
        model_name=model_info.name,
        dimension=model_info.dimension,
        index_version=1,
        query_instruction=model_info.query_instruction,
    )
    retrieval = DenseRetrievalService(
        document_service=document_service,
        embedding=embedding,
        vector_store=vector_store,
        index_version=1,
        default_top_k=5,
        max_top_k=20,
    )
    return document_service, retrieval, vector_store


def build_hybrid_services(
    root: Path,
    *,
    embedding: FakeEmbeddingModel | None = None,
):
    document_service, dense, vector_store = build_services(
        root,
        embedding=embedding,
    )
    model_info = dense.model_info
    bm25_store = BM25IndexStore(
        storage_dir=root / "bm25",
        embedding_model=model_info.name,
        index_version=1,
        k1=1.5,
        b=0.75,
    )
    hybrid = HybridRetrievalService(
        document_service=document_service,
        dense=dense,
        bm25=bm25_store,
        rrf_k=60,
        candidate_k=20,
        max_top_k=20,
    )
    return document_service, hybrid, vector_store, bm25_store


async def test_index_and_search_three_topics(tmp_path: Path) -> None:
    document_service, retrieval, store = build_services(tmp_path)
    try:
        redis_doc = await ingest_text(
            document_service,
            filename="redis.txt",
            text="Redis 用于缓存热点数据，需要处理缓存击穿和缓存失效。",
        )
        mysql_doc = await ingest_text(
            document_service,
            filename="mysql.txt",
            text="MySQL 保存订单业务数据，并通过事务保证一致性。",
        )
        rag_doc = await ingest_text(
            document_service,
            filename="rag.txt",
            text="RAG 先从知识库检索相关片段，再生成带来源的回答。",
        )
        for record in (redis_doc, mysql_doc, rag_doc):
            await retrieval.index_document(record.document_id)

        hits = await retrieval.search(query="缓存失效怎么处理", top_k=3)
        filtered = await retrieval.search(
            query="知识库检索",
            top_k=3,
            document_id=rag_doc.document_id,
        )

        assert hits[0].filename == "redis.txt"
        assert hits[0].score >= hits[1].score >= hits[2].score
        assert filtered
        assert all(hit.document_id == rag_doc.document_id for hit in filtered)
    finally:
        store.close()


async def test_repeated_index_uses_stable_points(tmp_path: Path) -> None:
    document_service, retrieval, store = build_services(tmp_path)
    try:
        record = await ingest_text(
            document_service,
            filename="cache.txt",
            text="Redis 缓存需要设置合理过期时间。",
        )

        first = await retrieval.index_document(record.document_id)
        second = await retrieval.index_document(record.document_id)

        assert first.indexed_parts == second.indexed_parts == 1
        assert store.count_document(record.document_id) == 1
    finally:
        store.close()


async def test_qdrant_index_survives_new_client(tmp_path: Path) -> None:
    document_service, retrieval, store = build_services(tmp_path)
    record = await ingest_text(
        document_service,
        filename="persist.txt",
        text="MySQL 订单数据库使用事务维护一致性。",
    )
    await retrieval.index_document(record.document_id)
    store.close()

    _, restarted, restarted_store = build_services(tmp_path)
    try:
        hits = await restarted.search(query="数据库事务", top_k=3)
        assert hits[0].document_id == record.document_id
        assert hits[0].filename == "persist.txt"
    finally:
        restarted_store.close()


async def test_long_chunks_are_split_without_losing_the_tail(
    tmp_path: Path,
) -> None:
    embedding = FakeEmbeddingModel(max_tokens=16, overlap_tokens=3)
    document_service, retrieval, store = build_services(
        tmp_path,
        embedding=embedding,
    )
    try:
        text = "Redis 缓存说明：" + ("缓存需要定期刷新并观察命中率。" * 4)
        record = await ingest_text(
            document_service,
            filename="long.txt",
            text=text,
        )
        summary = await retrieval.index_document(record.document_id)
        hits = await retrieval.search(
            query="Redis 缓存",
            top_k=20,
            document_id=record.document_id,
        )

        assert summary.indexed_parts > 1
        assert len(hits) == summary.indexed_parts
        assert {hit.chunk_id for hit in hits} == {
            record.chunks[0].chunk_id
        }
        assert hits[-1].content.endswith("。")
        assert hits[-1].part_count == summary.indexed_parts
    finally:
        store.close()


async def test_embedding_dimension_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    embedding = FakeEmbeddingModel(dimension=6, actual_dimension=5)
    document_service, retrieval, store = build_services(
        tmp_path,
        embedding=embedding,
    )
    try:
        record = await ingest_text(
            document_service,
            filename="dimension.txt",
            text="RAG 知识库向量。",
        )

        with pytest.raises(EmbeddingDimensionError):
            await retrieval.index_document(record.document_id)
    finally:
        store.close()


async def test_index_manifest_records_model_and_version(tmp_path: Path) -> None:
    document_service, retrieval, store = build_services(tmp_path)
    try:
        record = await ingest_text(
            document_service,
            filename="manifest.txt",
            text="RAG 检索测试。",
        )
        await retrieval.index_document(record.document_id)

        manifest_path = tmp_path / "qdrant-index-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["embedding_model"] == "fake-bge-small-zh-v1.5"
        assert manifest["vector_dimension"] == 6
        assert manifest["index_version"] == 1
        assert manifest["collection_name"] == store.collection_name
    finally:
        store.close()


async def test_api_index_search_and_validation_errors(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    try:
        record = await ingest_text(
            document_service,
            filename="api-redis.txt",
            text="Redis 提供缓存能力。",
        )

        unindexed = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存",
                "top_k": 3,
                "document_id": record.document_id,
            },
        )
        empty_query = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "   ", "top_k": 3},
        )
        invalid_index = await client.post(
            "/api/v1/documents/not-a-valid-id/index"
        )
        index_response = await client.post(
            f"/api/v1/documents/{record.document_id}/index"
        )
        search_response = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存", "top_k": 3},
        )
        too_many_results = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存", "top_k": 21},
        )
        default_search = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存"},
        )

        assert unindexed.status_code == 409
        assert unindexed.json()["error"]["code"] == "DOCUMENT_NOT_INDEXED"
        assert empty_query.status_code == 422
        assert invalid_index.status_code == 404
        assert index_response.status_code == 200
        assert index_response.json()["indexed_parts"] == 1
        assert search_response.status_code == 200
        assert search_response.json()["items"][0]["filename"] == "api-redis.txt"
        assert search_response.json()["embedding_model"] == (
            "fake-bge-small-zh-v1.5"
        )
        assert too_many_results.status_code == 422
        assert too_many_results.json()["error"]["code"] == (
            "INVALID_RETRIEVAL_PARAMETER"
        )
        assert default_search.status_code == 200
        assert default_search.json()["top_k"] == 5
        assert default_search.json()["mode"] == "dense"
    finally:
        store.close()


async def test_query_over_token_limit_returns_422(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    embedding = FakeEmbeddingModel(max_tokens=8)
    document_service, retrieval, store, _ = build_hybrid_services(
        tmp_path,
        embedding=embedding,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    try:
        record = await ingest_text(
            document_service,
            filename="query-limit.txt",
            text="RAG。",
        )
        await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "这是一个明显超过限制长度的问题", "top_k": 3},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "QUERY_TOKEN_LIMIT_EXCEEDED"
    finally:
        store.close()

