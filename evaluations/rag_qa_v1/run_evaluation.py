"""Run the isolated RAG v1 answer-quality evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
EVALUATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(EVALUATION_DIR))

from app.core.config import Settings  # noqa: E402
from app.llm.deepseek import DeepSeekLLM  # noqa: E402
from app.llm.budget import (  # noqa: E402
    LLMBudgetController,
    LLMBudgetLimits,
)
from app.rag.embeddings.bge import BgeEmbeddingModel  # noqa: E402
from app.rag.qa.context import EvidenceContextBuilder  # noqa: E402
from app.rag.qa.service import RagQAService  # noqa: E402
from app.rag.reranking.bge import BgeCrossEncoderReranker  # noqa: E402
from app.rag.reranking.service import RerankService  # noqa: E402
from app.rag.retrieval.bm25 import BM25IndexStore  # noqa: E402
from app.rag.retrieval.hybrid import HybridRetrievalService  # noqa: E402
from app.rag.retrieval.qdrant import QdrantVectorStore  # noqa: E402
from app.rag.retrieval.query import execute_retrieval  # noqa: E402
from app.rag.retrieval.service import DenseRetrievalService  # noqa: E402
from app.rag.retrieval.types import SearchMode  # noqa: E402
from app.rag.service import DocumentService  # noqa: E402
from app.rag.storage.local import LocalDocumentStore  # noqa: E402
from app.rag.types import DocumentRecord  # noqa: E402

from rag_metrics import (  # noqa: E402
    compare_modes,
    markdown_report,
    mode_summary,
    score_response,
)

DATA_PATH = EVALUATION_DIR / "data" / "questions_v1.json"
RESULTS_DIR = EVALUATION_DIR / "results"
PROMPT_PATH = (
    BACKEND_ROOT / "app" / "prompts" / "system" / "rag_answer_system.txt"
)


async def content_iterator(data: bytes) -> AsyncIterator[bytes]:
    yield data


def load_dataset() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def validate_dataset(dataset: dict[str, Any]) -> None:
    questions = dataset["questions"]
    if len(questions) != 50:
        raise ValueError(f"Expected 50 questions, found {len(questions)}")
    answerable = [
        item for item in questions
        if item["answerability"] == "answerable"
    ]
    unanswerable = [
        item for item in questions
        if item["answerability"] == "unanswerable"
    ]
    if len(answerable) != 30 or len(unanswerable) != 20:
        raise ValueError(
            "Expected 30 answerable and 20 unanswerable questions"
        )
    attacks = [item for item in questions if item.get("attack_type")]
    if len(attacks) < 5:
        raise ValueError("At least 5 attack/conflict questions are required")
    for question in questions:
        if question.get("human_verified") is not True:
            raise ValueError(
                f"Question {question['id']} is not human verified"
            )
        if (
            question["answerability"] == "answerable"
            and not question.get("expected_facts")
        ):
            raise ValueError(
                f"Answerable question {question['id']} has no expected facts"
            )
    manifest_paths = [
        PROJECT_ROOT / item["path"]
        for item in dataset["document_manifest"]
    ]
    missing = [str(path) for path in manifest_paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing evaluation documents: {missing}")


def build_llm(
    settings: Settings,
) -> tuple[DeepSeekLLM, LLMBudgetController]:
    if settings.deepseek_api_key is None:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    api_key = settings.deepseek_api_key.get_secret_value().strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is empty")
    budget = LLMBudgetController(
        LLMBudgetLimits(
            enabled=True,
            max_requests=int(os.getenv("RAG_QA_MAX_REQUESTS", "0")),
            max_tokens=int(os.getenv("RAG_QA_MAX_TOKENS", "0")),
            max_cost_usd=float(
                os.getenv("RAG_QA_MAX_COST_USD", "0")
            ),
            max_output_tokens=int(
                os.getenv("RAG_QA_MAX_OUTPUT_TOKENS", "1024")
            ),
            input_cost_per_million_usd=float(
                os.getenv(
                    "RAG_QA_INPUT_COST_PER_MILLION_USD",
                    "0",
                )
            ),
            output_cost_per_million_usd=float(
                os.getenv(
                    "RAG_QA_OUTPUT_COST_PER_MILLION_USD",
                    "0",
                )
            ),
        )
    )
    return (
        DeepSeekLLM(
            api_key=api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            timeout_seconds=float(
                os.getenv("RAG_QA_TIMEOUT_SECONDS", "60")
            ),
            max_retries=int(os.getenv("RAG_QA_MAX_RETRIES", "0")),
            temperature=settings.llm_temperature,
            budget=budget,
        ),
        budget,
    )


def manifest_hash(manifest: list[dict[str, str]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(manifest, key=lambda value: value["key"]):
        path = PROJECT_ROOT / item["path"]
        digest.update(item["key"].encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def serialize_hit(hit: Any, document_id_to_key: dict[str, str]) -> dict[str, Any]:
    unit = hit.unit
    stem = Path(unit.filename).stem
    return {
        "rank": hit.rank,
        "score": hit.final_score,
        "document_id": unit.document_id,
        "document_key": document_id_to_key[unit.document_id],
        "chunk_id": unit.chunk_id,
        "chunk_key": f"chunk:{stem}:{unit.chunk_index}",
        "filename": unit.filename,
        "page_number": unit.page_number,
        "chunk_index": unit.chunk_index,
        "part_index": unit.part_index,
        "content": unit.content,
        "dense_rank": hit.dense_rank,
        "dense_score": hit.dense_score,
        "bm25_rank": hit.bm25_rank,
        "bm25_score": hit.bm25_score,
        "retrieval_rank": hit.retrieval_rank,
        "retrieval_score": hit.retrieval_score,
        "rerank_score": hit.rerank_score,
    }


def resolve_gold(
    question: dict[str, Any],
    document_key_to_id: dict[str, str],
    chunk_key_to_id: dict[str, str],
) -> tuple[list[str], list[str]]:
    resolved_documents = []
    resolved_chunks = []
    for document_key in question.get("gold_document_ids", []):
        if document_key not in document_key_to_id:
            raise ValueError(
                f"Unknown gold document key {document_key}"
            )
        resolved_documents.append(document_key_to_id[document_key])
    for chunk_key in question.get("gold_chunk_ids", []):
        if chunk_key not in chunk_key_to_id:
            raise ValueError(f"Unknown gold chunk key {chunk_key}")
        resolved_chunks.append(chunk_key_to_id[chunk_key])
    return resolved_documents, resolved_chunks


def failure_analysis(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "citation_valid_but_fact_not_fully_supported": [
            row["id"]
            for row in rows
            if row["answerability"] == "answerable"
            and row["answered"]
            and row["citation_valid"]
            and not row["fully_correct"]
        ],
        "gold_evidence_retrieved_but_refused": [
            row["id"]
            for row in rows
            if row["answerability"] == "answerable"
            and not row["answered"]
            and bool(
                set(hit["chunk_key"] for hit in row["retrieval_hits"][:5])
                & set(row["gold_chunk_keys"])
            )
        ],
        "multi_source_or_multichunk_omissions": [
            row["id"]
            for row in rows
            if row["category"] in {
                "multi_document",
                "multi_chunk",
                "multi_paragraph",
            }
            and row["answered"]
            and row["answer_completeness"] < 1.0
        ],
        "unsupported_answers_on_unanswerable": [
            row["id"]
            for row in rows
            if row["answerability"] == "unanswerable"
            and row["answered"]
            and not row.get("safe_refusal")
        ],
        "unsafe_attack_questions_answered": [
            row["id"]
            for row in rows
            if row.get("attack_type")
            and row["expected_behavior"] == "refuse"
            and not row.get("safe_refusal")
        ],
    }


async def evaluate_mode(
    *,
    mode_name: str,
    rerank: bool,
    dataset: dict[str, Any],
    retrieval: HybridRetrievalService,
    rerank_service: RerankService,
    rag_service: RagQAService,
    document_key_to_id: dict[str, str],
    document_id_to_key: dict[str, str],
    chunk_key_to_id: dict[str, str],
    settings: Settings,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, question in enumerate(dataset["questions"], start=1):
        resolved_documents, resolved_chunks = resolve_gold(
            question,
            document_key_to_id,
            chunk_key_to_id,
        )
        execution = await execute_retrieval(
            retrieval=retrieval,
            rerank_service=rerank_service,
            query=question["question"],
            top_k=settings.rag_retrieval_default_top_k,
            mode=SearchMode.HYBRID,
            rerank=rerank,
            candidate_k=settings.reranker_candidate_k if rerank else None,
            document_id=None,
        )
        retrieval_hits = [
            serialize_hit(hit, document_id_to_key)
            for hit in execution.hits
        ]
        full_source_content = {
            (hit.unit.chunk_id, hit.unit.part_index): hit.unit.content
            for hit in execution.hits
        }
        response_model = await rag_service.ask(
            query=question["question"],
            top_k=settings.rag_retrieval_default_top_k,
            mode=SearchMode.HYBRID,
            rerank=rerank,
            candidate_k=(
                settings.reranker_candidate_k if rerank else None
            ),
            document_id=None,
        )
        response = response_model.model_dump(mode="json")
        score = score_response(
            question=question,
            response=response,
            full_source_content=full_source_content,
        )
        row = {
            "id": question["id"],
            "question": question["question"],
            "answerability": question["answerability"],
            "expected_behavior": question["expected_behavior"],
            "gold_answer": question["gold_answer"],
            "expected_facts": question["expected_facts"],
            "gold_document_keys": question["gold_document_ids"],
            "gold_chunk_keys": question["gold_chunk_ids"],
            "resolved_gold_document_ids": resolved_documents,
            "resolved_gold_chunk_ids": resolved_chunks,
            "difficulty": question["difficulty"],
            "category": question["category"],
            "attack_type": question["attack_type"],
            "human_verified": question["human_verified"],
            "mode": mode_name,
            "retrieval_hits": retrieval_hits,
            "response": response,
            "latency": response["latency_ms"],
            "usage": response.get("usage"),
            "model": response.get("model"),
            **score,
        }
        rows.append(row)
        if index % 5 == 0:
            print(
                f"{mode_name}: {index}/{len(dataset['questions'])}",
                flush=True,
            )
    return rows


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    dataset = load_dataset()
    validate_dataset(dataset)
    estimated_requests = len(dataset["questions"]) * 2
    if args.validate_only:
        print("rag-qa-evaluation-data: valid")
        print("estimated-model-requests:", estimated_requests)
        return 0
    if os.getenv("RUN_REAL_RAG_QA_EVALS") != "1" or not args.real:
        print(
            "Real RAG QA evaluation is disabled. Set "
            "RUN_REAL_RAG_QA_EVALS=1 and pass --real to consume API quota."
        )
        return 2

    max_requests = int(os.getenv("RAG_QA_MAX_REQUESTS", "0"))
    max_tokens = int(os.getenv("RAG_QA_MAX_TOKENS", "0"))
    max_cost = float(os.getenv("RAG_QA_MAX_COST_USD", "0"))
    input_rate = float(
        os.getenv("RAG_QA_INPUT_COST_PER_MILLION_USD", "0")
    )
    output_rate = float(
        os.getenv("RAG_QA_OUTPUT_COST_PER_MILLION_USD", "0")
    )
    if estimated_requests > max_requests:
        raise RuntimeError(
            f"Estimated model requests {estimated_requests} exceed "
            f"limit {max_requests}"
        )
    if (
        max_tokens <= 0
        or max_cost <= 0
        or input_rate <= 0
        or output_rate <= 0
    ):
        raise RuntimeError(
            "Real RAG QA evaluation requires positive token, cost, "
            "input-rate, and output-rate budgets."
        )
    settings = Settings()
    llm, budget = build_llm(settings)
    run_id = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    runtime_root = (
        PROJECT_ROOT / "storage" / "e2e" / "rag_qa_v1" / run_id
    )
    documents_dir = runtime_root / "documents"
    qdrant_dir = runtime_root / "qdrant"
    bm25_dir = runtime_root / "bm25"
    documents_dir.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

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
    document_service = DocumentService(
        store=LocalDocumentStore(documents_dir),
        max_upload_bytes=settings.document_max_upload_bytes,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    model_info = embedding.info
    vector_store = QdrantVectorStore(
        storage_dir=qdrant_dir,
        model_name=model_info.name,
        dimension=model_info.dimension,
        index_version=settings.rag_index_version,
        query_instruction=model_info.query_instruction,
    )
    bm25_store = BM25IndexStore(
        storage_dir=bm25_dir,
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
        default_top_k=settings.rag_retrieval_default_top_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )
    retrieval = HybridRetrievalService(
        document_service=document_service,
        dense=dense,
        bm25=bm25_store,
        rrf_k=settings.rag_rrf_k,
        candidate_k=settings.rag_rrf_candidate_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )
    rerank_service = RerankService(
        reranker=reranker,
        default_candidate_k=settings.reranker_candidate_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )
    rag_service = RagQAService(
        retrieval=retrieval,
        rerank_service=rerank_service,
        llm=llm,
        system_prompt=PROMPT_PATH.read_text(encoding="utf-8").strip(),
        context_builder=EvidenceContextBuilder(
            max_tokens=settings.rag_context_max_tokens,
            count_tokens=embedding.count_tokens,
        ),
        source_summary_chars=settings.rag_source_summary_chars,
    )

    document_key_to_id: dict[str, str] = {}
    document_id_to_key: dict[str, str] = {}
    chunk_key_to_id: dict[str, str] = {}
    chunk_count = 0
    records: list[DocumentRecord] = []
    try:
        for manifest in dataset["document_manifest"]:
            path = PROJECT_ROOT / manifest["path"]
            record = await document_service.ingest(
                filename=path.name,
                content_type="text/plain",
                content=content_iterator(path.read_bytes()),
            )
            records.append(record)
            document_key_to_id[manifest["key"]] = record.document_id
            document_id_to_key[record.document_id] = manifest["key"]
            chunk_count += record.chunk_count
            for chunk in record.chunks:
                stem = Path(chunk.filename).stem
                chunk_key_to_id[
                    f"chunk:{stem}:{chunk.chunk_index}"
                ] = chunk.chunk_id
        for record in records:
            await retrieval.index_document(record.document_id)

        # Validate every manually labeled gold Chunk after indexing.
        for question in dataset["questions"]:
            resolve_gold(
                question,
                document_key_to_id,
                chunk_key_to_id,
            )

        await execute_retrieval(
            retrieval=retrieval,
            rerank_service=rerank_service,
            query="系统故障",
            top_k=settings.rag_retrieval_default_top_k,
            mode=SearchMode.HYBRID,
            rerank=True,
            candidate_k=settings.reranker_candidate_k,
            document_id=None,
        )

        mode_rows = {}
        for mode_name, rerank in (
            ("hybrid", False),
            ("hybrid_reranker", True),
        ):
            mode_rows[mode_name] = await evaluate_mode(
                mode_name=mode_name,
                rerank=rerank,
                dataset=dataset,
                retrieval=retrieval,
                rerank_service=rerank_service,
                rag_service=rag_service,
                document_key_to_id=document_key_to_id,
                document_id_to_key=document_id_to_key,
                chunk_key_to_id=chunk_key_to_id,
                settings=settings,
            )
    finally:
        budget_snapshot = await budget.snapshot()
        vector_store.close()
        await llm.aclose()

    modes = {
        mode_name: mode_summary(rows)
        for mode_name, rows in mode_rows.items()
    }
    comparison = compare_modes(
        modes["hybrid"],
        modes["hybrid_reranker"],
    )
    analyses = {
        mode_name: failure_analysis(rows)
        for mode_name, rows in mode_rows.items()
    }
    hybrid_by_id = {
        row["id"]: row for row in mode_rows["hybrid"]
    }
    reranked_by_id = {
        row["id"]: row for row in mode_rows["hybrid_reranker"]
    }
    fixed_by_reranker = [
        question_id
        for question_id in hybrid_by_id
        if (
            reranked_by_id[question_id]["answer_completeness"]
            > hybrid_by_id[question_id]["answer_completeness"]
        )
    ]
    regressed_by_reranker = [
        question_id
        for question_id in hybrid_by_id
        if (
            reranked_by_id[question_id]["answer_completeness"]
            < hybrid_by_id[question_id]["answer_completeness"]
        )
    ]
    observed_models = sorted(
        {
            row["model"]
            for rows in mode_rows.values()
            for row in rows
            if row.get("model")
        }
    )
    category_counts = {
        category: sum(
            1 for question in dataset["questions"]
            if question["category"] == category
        )
        for category in sorted(
            {question["category"] for question in dataset["questions"]}
        )
    }
    result = {
        "metadata": {
            "run_id": run_id,
            "run_date": datetime.now(timezone.utc).isoformat(),
            "configured_model": settings.deepseek_model,
            "observed_models": observed_models,
            "embedding_model": model_info.name,
            "embedding_dimension": model_info.dimension,
            "reranker_model": settings.reranker_model_name,
            "top_k": settings.rag_retrieval_default_top_k,
            "candidate_k": settings.reranker_candidate_k,
            "temperature": settings.llm_temperature,
            "max_retries": int(os.getenv("RAG_QA_MAX_RETRIES", "0")),
            "estimated_model_requests": estimated_requests,
            "max_model_requests": max_requests,
            "llm_budget": budget_snapshot,
            "runtime_root": str(runtime_root),
            "prompt_sha256_16": hashlib.sha256(
                PROMPT_PATH.read_bytes()
            ).hexdigest()[:16],
        },
        "dataset": {
            "version": dataset["version"],
            "document_count": len(records),
            "chunk_count": chunk_count,
            "document_manifest_sha256": manifest_hash(
                dataset["document_manifest"]
            ),
            "question_count": len(dataset["questions"]),
            "answerable_count": sum(
                1 for q in dataset["questions"]
                if q["answerability"] == "answerable"
            ),
            "unanswerable_count": sum(
                1 for q in dataset["questions"]
                if q["answerability"] == "unanswerable"
            ),
            "attack_count": sum(
                1 for q in dataset["questions"] if q.get("attack_type")
            ),
            "category_counts": category_counts,
            "chunk_inventory": {
                manifest["key"]: [
                    chunk_key
                    for chunk_key in chunk_key_to_id
                    if chunk_key.startswith(
                        f"chunk:{Path(manifest['path']).stem}:"
                    )
                ]
                for manifest in dataset["document_manifest"]
            },
        },
        "modes": modes,
        "comparison": comparison,
        "analysis": {
            "failures_by_mode": analyses,
            "fixed_by_reranker": fixed_by_reranker,
            "regressed_by_reranker": regressed_by_reranker,
        },
        "results": mode_rows,
    }
    json_path = RESULTS_DIR / f"{run_id}.json"
    markdown_path = RESULTS_DIR / f"{run_id}.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        markdown_report(result),
        encoding="utf-8",
    )
    print(f"results-json: {json_path}")
    print(f"results-markdown: {markdown_path}")
    for mode_name in ("hybrid", "hybrid_reranker"):
        print(
            f"{mode_name}-answer-correctness:",
            f"{modes[mode_name]['answers']['answer_correctness']:.4f}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
