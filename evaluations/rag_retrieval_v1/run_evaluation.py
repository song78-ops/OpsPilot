"""Run the manually labeled Dense/BM25/Hybrid retrieval evaluation."""

import json
import math
import statistics
import sys
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from app.rag.embeddings.bge import BgeEmbeddingModel  # noqa: E402
from app.rag.retrieval.bm25 import BM25IndexStore  # noqa: E402
from app.rag.retrieval.hybrid import HybridRetrievalService  # noqa: E402
from app.rag.retrieval.qdrant import QdrantVectorStore  # noqa: E402
from app.rag.retrieval.service import DenseRetrievalService  # noqa: E402
from app.rag.retrieval.types import SearchMode  # noqa: E402
from app.rag.reranking.bge import BgeCrossEncoderReranker  # noqa: E402
from app.rag.reranking.service import RerankService  # noqa: E402
from app.rag.service import DocumentService  # noqa: E402
from app.rag.storage.local import LocalDocumentStore  # noqa: E402

EVALUATION_DIR = Path(__file__).resolve().parent
DOCUMENTS_DIR = EVALUATION_DIR / "documents"
QUESTIONS_PATH = EVALUATION_DIR / "questions.json"


async def content_iterator(data: bytes) -> AsyncIterator[bytes]:
    yield data


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, round((len(ordered) - 1) * ratio))
    return ordered[index]


def score_mode(
    *,
    mode: str,
    queries: list[dict[str, Any]],
    per_query: dict[str, list[dict[str, Any]]],
    latencies: dict[str, list[float]],
) -> dict[str, Any]:
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    no_answer_returned = 0
    no_answer_total = 0
    by_type: dict[str, dict[str, float]] = {}

    for query in queries:
        relevant = set(query["relevant_documents"])
        items = per_query[query["id"]]
        documents = []
        for item in items:
            document_key = Path(item["filename"]).stem
            if document_key not in documents:
                documents.append(document_key)

        if relevant:
            recall = len(set(documents[:3]) & relevant) / len(relevant)
            reciprocal_rank = 0.0
            for rank, document_key in enumerate(documents[:5], start=1):
                if document_key in relevant:
                    reciprocal_rank = 1.0 / rank
                    break
            dcg = sum(
                1.0 / (math.log2(rank + 1))
                for rank, document_key in enumerate(documents[:5], start=1)
                if document_key in relevant
            )
            ideal = sum(
                1.0 / math.log2(rank + 1)
                for rank in range(1, min(len(relevant), 5) + 1)
            )
            ndcg = dcg / ideal
            recalls.append(recall)
            reciprocal_ranks.append(reciprocal_rank)
            ndcgs.append(ndcg)

            group = by_type.setdefault(
                query["type"],
                {"count": 0, "recall": 0.0, "mrr": 0.0, "ndcg": 0.0},
            )
            group["count"] += 1
            group["recall"] += recall
            group["mrr"] += reciprocal_rank
            group["ndcg"] += ndcg
        else:
            no_answer_total += 1
            if items:
                no_answer_returned += 1

    for group in by_type.values():
        count = int(group["count"])
        group["recall"] /= count
        group["mrr"] /= count
        group["ndcg"] /= count

    latency = latencies[mode]
    return {
        "mode": mode,
        "recall_at_3": statistics.mean(recalls),
        "mrr_at_5": statistics.mean(reciprocal_ranks),
        "ndcg_at_5": statistics.mean(ndcgs),
        "mean_latency_ms": statistics.mean(latency) * 1000,
        "p50_latency_ms": percentile(latency, 0.50) * 1000,
        "p95_latency_ms": percentile(latency, 0.95) * 1000,
        "no_answer_total": no_answer_total,
        "no_answer_returned_any": no_answer_returned,
        "by_type": by_type,
    }


async def main() -> int:
    settings = Settings()
    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))["queries"]
    embedding = BgeEmbeddingModel(
        model_name=settings.embedding_model_name,
        cache_dir=settings.resolved_model_cache_dir,
        batch_size=settings.embedding_batch_size,
        max_tokens=settings.embedding_max_tokens,
        overlap_tokens=settings.embedding_overlap_tokens,
        query_instruction=settings.embedding_query_instruction,
    )
    reranker = BgeCrossEncoderReranker(
        model_name=settings.reranker_model_name,
        cache_dir=settings.resolved_model_cache_dir,
        batch_size=settings.reranker_batch_size,
        max_length=settings.reranker_max_length,
        overlap_tokens=settings.reranker_overlap_tokens,
    )

    with tempfile.TemporaryDirectory(prefix="opspilot-rag-eval-") as temp:
        runtime = Path(temp)
        document_service = DocumentService(
            store=LocalDocumentStore(runtime / "documents"),
            max_upload_bytes=settings.document_max_upload_bytes,
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
        )
        model_info = embedding.info
        vector_store = QdrantVectorStore(
            storage_dir=runtime / "qdrant",
            model_name=model_info.name,
            dimension=model_info.dimension,
            index_version=settings.rag_index_version,
            query_instruction=model_info.query_instruction,
        )
        bm25_store = BM25IndexStore(
            storage_dir=runtime / "bm25",
            embedding_model=model_info.name,
            index_version=settings.rag_index_version,
            k1=settings.bm25_k1,
            b=settings.bm25_b,
        )
        dense = DenseRetrievalService(
            document_service=document_service,
            embedding=embedding,
            vector_store=vector_store,
            index_version=settings.rag_index_version,
            default_top_k=5,
            max_top_k=20,
        )
        retrieval = HybridRetrievalService(
            document_service=document_service,
            dense=dense,
            bm25=bm25_store,
            rrf_k=settings.rag_rrf_k,
            candidate_k=settings.rag_rrf_candidate_k,
            max_top_k=20,
        )
        rerank_service = RerankService(
            reranker=reranker,
            default_candidate_k=settings.reranker_candidate_k,
            max_top_k=20,
        )
        load_started = time.perf_counter()
        reranker.info
        reranker_load_ms = (time.perf_counter() - load_started) * 1000

        try:
            for path in sorted(DOCUMENTS_DIR.glob("*.txt")):
                await document_service.ingest(
                    filename=path.name,
                    content_type="text/plain",
                    content=content_iterator(path.read_bytes()),
                )
            for record in await document_service.list_documents():
                await retrieval.index_document(record.document_id)

            for mode in SearchMode:
                await retrieval.search(
                    query="系统故障排查",
                    top_k=5,
                    mode=mode,
                )

            per_query: dict[str, dict[str, list[dict[str, Any]]]] = {
                "dense": {},
                "bm25": {},
                "hybrid": {},
                "hybrid_reranker": {},
            }
            latencies: dict[str, list[float]] = {
                "dense": [],
                "bm25": [],
                "hybrid": [],
                "hybrid_reranker": [],
            }
            detail: dict[str, list[dict[str, Any]]] = {
                "dense": [],
                "bm25": [],
                "hybrid": [],
                "hybrid_reranker": [],
            }

            for query in questions:
                for mode in SearchMode:
                    started = time.perf_counter()
                    hits = await retrieval.search(
                        query=query["question"],
                        top_k=5,
                        mode=mode,
                    )
                    elapsed = time.perf_counter() - started
                    latencies[mode.value].append(elapsed)
                    serialized = [
                        {
                            "rank": hit.rank,
                            "score": hit.final_score,
                            "document_id": hit.unit.document_id,
                            "chunk_id": hit.unit.chunk_id,
                            "part_index": hit.unit.part_index,
                            "filename": hit.unit.filename,
                            "page_number": hit.unit.page_number,
                            "chunk_index": hit.unit.chunk_index,
                            "content": hit.unit.content,
                            "dense_rank": hit.dense_rank,
                            "dense_score": hit.dense_score,
                            "bm25_rank": hit.bm25_rank,
                            "bm25_score": hit.bm25_score,
                        }
                        for hit in hits
                    ]
                    per_query[mode.value][query["id"]] = serialized
                    detail[mode.value].append(
                        {
                            "id": query["id"],
                            "type": query["type"],
                            "question": query["question"],
                            "relevant_documents": query["relevant_documents"],
                            "latency_ms": elapsed * 1000,
                            "items": serialized,
                        }
                    )

                started = time.perf_counter()
                candidate_hits = await retrieval.search(
                    query=query["question"],
                    top_k=settings.reranker_candidate_k,
                    mode=SearchMode.HYBRID,
                )
                reranked_hits, _ = await rerank_service.rerank(
                    query=query["question"],
                    hits=candidate_hits,
                    top_k=5,
                    candidate_k=settings.reranker_candidate_k,
                )
                elapsed = time.perf_counter() - started
                latencies["hybrid_reranker"].append(elapsed)
                serialized = [
                    {
                        "rank": hit.rank,
                        "score": hit.final_score,
                        "document_id": hit.unit.document_id,
                        "chunk_id": hit.unit.chunk_id,
                        "part_index": hit.unit.part_index,
                        "filename": hit.unit.filename,
                        "page_number": hit.unit.page_number,
                        "chunk_index": hit.unit.chunk_index,
                        "content": hit.unit.content,
                        "dense_rank": hit.dense_rank,
                        "dense_score": hit.dense_score,
                        "bm25_rank": hit.bm25_rank,
                        "bm25_score": hit.bm25_score,
                        "retrieval_rank": hit.retrieval_rank,
                        "retrieval_score": hit.retrieval_score,
                        "rerank_score": hit.rerank_score,
                    }
                    for hit in reranked_hits
                ]
                per_query["hybrid_reranker"][query["id"]] = serialized
                detail["hybrid_reranker"].append(
                    {
                        "id": query["id"],
                        "type": query["type"],
                        "question": query["question"],
                        "relevant_documents": query["relevant_documents"],
                        "latency_ms": elapsed * 1000,
                        "items": serialized,
                    }
                )

            single_document = (
                "Redis 缓存击穿可以通过互斥锁和逻辑过期处理。"
            )
            reranker.score_pairs("缓存击穿", [single_document])
            single_started = time.perf_counter()
            reranker.score_pairs("缓存击穿", [single_document])
            single_inference_ms = (time.perf_counter() - single_started) * 1000
            batch_documents = [
                f"缓存与数据库主题文档第 {index} 段。"
                for index in range(10)
            ]
            batch_started = time.perf_counter()
            reranker.score_pairs("缓存击穿和数据库一致性", batch_documents)
            batch_10_inference_ms = (
                time.perf_counter() - batch_started
            ) * 1000

            candidate_benchmark: dict[str, dict[str, float]] = {}
            benchmark_ids = {
                "q01",
                "q07",
                "q12",
                "q13",
                "q17",
                "q20",
                "q21",
                "q23",
                "q25",
                "q26",
            }
            benchmark_queries = [
                query
                for query in questions
                if query["id"] in benchmark_ids
            ]
            for candidate_k in (5, 10, 20):
                candidate_latencies: list[float] = []
                for query in benchmark_queries:
                    started = time.perf_counter()
                    hits = await retrieval.search(
                        query=query["question"],
                        top_k=candidate_k,
                        mode=SearchMode.HYBRID,
                    )
                    await rerank_service.rerank(
                        query=query["question"],
                        hits=hits,
                        top_k=5,
                        candidate_k=candidate_k,
                    )
                    candidate_latencies.append(
                        time.perf_counter() - started
                    )
                candidate_benchmark[f"candidate_k={candidate_k}"] = {
                    "mean_ms": statistics.mean(candidate_latencies) * 1000,
                    "p50_ms": percentile(candidate_latencies, 0.50) * 1000,
                    "p95_ms": percentile(candidate_latencies, 0.95) * 1000,
                }

            modes = ("dense", "bm25", "hybrid", "hybrid_reranker")
            metrics = [
                score_mode(
                    mode=mode,
                    queries=questions,
                    per_query=per_query[mode],
                    latencies=latencies,
                )
                for mode in modes
            ]
            report = {
                "dataset": {
                    "documents": len(list(DOCUMENTS_DIR.glob("*.txt"))),
                    "queries": len(questions),
                    "rrf_k": settings.rag_rrf_k,
                    "chunk_size": settings.rag_chunk_size,
                    "chunk_overlap": settings.rag_chunk_overlap,
                    "reranker_model": settings.reranker_model_name,
                    "reranker_batch_size": settings.reranker_batch_size,
                    "reranker_candidate_k": settings.reranker_candidate_k,
                },
                "metrics": metrics,
                "reranker_performance": {
                    "load_ms": reranker_load_ms,
                    "single_inference_ms": single_inference_ms,
                    "batch_10_inference_ms": batch_10_inference_ms,
                    "candidate_benchmark": candidate_benchmark,
                },
                "results": detail,
            }
            json_path = EVALUATION_DIR / "latest_results.json"
            json_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            lines = [
                "# RAG Retrieval Evaluation Results",
                "",
                "| Mode | Recall@3 | MRR@5 | nDCG@5 | Mean ms | P50 ms | P95 ms | No-answer returns |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
            for metric in metrics:
                lines.append(
                    f"| {metric['mode']} | {metric['recall_at_3']:.4f} | "
                    f"{metric['mrr_at_5']:.4f} | {metric['ndcg_at_5']:.4f} | "
                    f"{metric['mean_latency_ms']:.2f} | "
                    f"{metric['p50_latency_ms']:.2f} | "
                    f"{metric['p95_latency_ms']:.2f} | "
                    f"{metric['no_answer_returned_any']}/"
                    f"{metric['no_answer_total']} |"
                )
            lines.extend(
                [
                    "",
                    "## Reranker Performance",
                    "",
                    f"- Load: {reranker_load_ms:.2f} ms",
                    f"- Warm single inference: {single_inference_ms:.2f} ms",
                    f"- Batch 10 inference: {batch_10_inference_ms:.2f} ms",
                    "",
                    "| Candidate K | Mean ms | P50 ms | P95 ms |",
                    "|---:|---:|---:|---:|",
                ]
            )
            for name, values in candidate_benchmark.items():
                lines.append(
                    f"| {name.split('=')[1]} | {values['mean_ms']:.2f} | "
                    f"{values['p50_ms']:.2f} | {values['p95_ms']:.2f} |"
                )
            (EVALUATION_DIR / "latest_results.md").write_text(
                "\n".join(lines) + "\n",
                encoding="utf-8",
            )
            print("\n".join(lines))
            print(f"\nJSON: {json_path}")
            return 0
        finally:
            vector_store.close()


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))

