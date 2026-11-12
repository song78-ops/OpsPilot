"""Offline reranking API and service tests."""

from pathlib import Path

import httpx

from app.api.deps import get_rerank_service, get_retrieval_service
from app.main import app
from app.rag.exceptions import RerankerUnavailableError
from app.rag.reranking.service import RerankService
from tests.fakes import FakeReranker
from tests.test_retrieval import build_hybrid_services, ingest_text


async def test_rerank_reorders_and_preserves_original_scores(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    reranker = FakeReranker(
        keyword_scores={
            "MySQL": 4.5,
            "Redis": 1.0,
        }
    )
    rerank_service = RerankService(
        reranker=reranker,
        default_candidate_k=5,
        max_top_k=20,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    app.dependency_overrides[get_rerank_service] = lambda: rerank_service
    try:
        redis_doc = await ingest_text(
            document_service,
            filename="redis-rerank.txt",
            text="Redis 缓存击穿和缓存重建。",
        )
        mysql_doc = await ingest_text(
            document_service,
            filename="mysql-rerank.txt",
            text="MySQL 订单事务和数据库一致性。",
        )
        for record in (redis_doc, mysql_doc):
            await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存",
                "top_k": 1,
                "mode": "hybrid",
                "rerank": True,
                "candidate_k": 2,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["rerank_requested"] is True
        assert body["rerank_applied"] is True
        assert body["rerank_model"] == "fake-bge-reranker-base"
        assert body["candidate_k"] == 2
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["filename"] == "mysql-rerank.txt"
        assert item["rerank_score"] == 4.5
        assert item["score"] == 4.5
        assert item["retrieval_rank"] == 2
        assert item["retrieval_score"] is not None
        assert len(reranker.calls) == 1
        assert len(reranker.calls[0]) == 2
    finally:
        store.close()


async def test_rerank_false_keeps_legacy_retrieval_response(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    try:
        record = await ingest_text(
            document_service,
            filename="legacy.txt",
            text="Redis 缓存。",
        )
        await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "缓存", "mode": "dense", "top_k": 1},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["rerank_requested"] is False
        assert body["rerank_applied"] is False
        assert body["candidate_k"] == 1
        item = body["items"][0]
        assert item["rerank_score"] is None
        assert item["retrieval_rank"] == item["rank"]
        assert item["retrieval_score"] == item["score"]
    finally:
        store.close()


async def test_rerank_candidate_k_must_not_be_smaller_than_top_k(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    rerank_service = RerankService(
        reranker=FakeReranker(),
        default_candidate_k=20,
        max_top_k=20,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    app.dependency_overrides[get_rerank_service] = lambda: rerank_service
    try:
        record = await ingest_text(
            document_service,
            filename="candidate.txt",
            text="Redis 缓存。",
        )
        await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存",
                "top_k": 3,
                "candidate_k": 2,
                "rerank": True,
            },
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_RETRIEVAL_PARAMETER"
    finally:
        store.close()


async def test_reranker_failure_is_explicit_without_fallback(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    rerank_service = RerankService(
        reranker=FakeReranker(
            error=RerankerUnavailableError("model unavailable")
        ),
        default_candidate_k=5,
        max_top_k=20,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    app.dependency_overrides[get_rerank_service] = lambda: rerank_service
    try:
        record = await ingest_text(
            document_service,
            filename="rerank-failure.txt",
            text="Redis 缓存。",
        )
        await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存",
                "top_k": 1,
                "rerank": True,
                "candidate_k": 1,
            },
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RERANKER_UNAVAILABLE"
    finally:
        store.close()


async def test_disabled_reranker_returns_explicit_error(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    document_service, retrieval, store, _ = build_hybrid_services(tmp_path)
    rerank_service = RerankService(
        reranker=None,
        default_candidate_k=5,
        max_top_k=20,
    )
    app.dependency_overrides[get_retrieval_service] = lambda: retrieval
    app.dependency_overrides[get_rerank_service] = lambda: rerank_service
    try:
        record = await ingest_text(
            document_service,
            filename="disabled.txt",
            text="Redis 缓存。",
        )
        await retrieval.index_document(record.document_id)

        response = await client.post(
            "/api/v1/retrieval/search",
            json={
                "query": "缓存",
                "top_k": 1,
                "candidate_k": 1,
                "rerank": True,
            },
        )

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "RERANKER_UNAVAILABLE"
    finally:
        store.close()

