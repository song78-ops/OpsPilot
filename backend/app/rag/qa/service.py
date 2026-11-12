"""Grounded non-streaming knowledge-base answer generation."""

import json
import logging
import re
import time
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.llm.base import LLMProvider
from app.rag.qa.context import EvidenceContextBuilder
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.retrieval.query import execute_retrieval
from app.rag.retrieval.types import SearchMode
from app.rag.reranking.service import RerankService
from app.schemas.chat import TokenUsage
from app.schemas.rag import (
    RagAskResponse,
    RagLatencyResponse,
    RagSourceResponse,
)

logger = logging.getLogger(__name__)
_CITATION_PATTERN = re.compile(r"\[([1-9][0-9]*)\]")


class _ModelAnswerPayload(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str = ""
    used_citations: list[int] = []
    evidence_assessment: str = ""


class RagQAService:
    """Retrieve evidence, request a grounded answer, and validate citations."""

    def __init__(
        self,
        *,
        retrieval: HybridRetrievalService,
        rerank_service: RerankService,
        llm: LLMProvider,
        system_prompt: str,
        context_builder: EvidenceContextBuilder,
        source_summary_chars: int,
    ) -> None:
        self._retrieval = retrieval
        self._rerank_service = rerank_service
        self._llm = llm
        self._system_prompt = system_prompt
        self._context_builder = context_builder
        self._source_summary_chars = source_summary_chars

    async def ask(
        self,
        *,
        query: str,
        top_k: int | None,
        mode: SearchMode,
        rerank: bool,
        candidate_k: int | None,
        document_id: str | None,
    ) -> RagAskResponse:
        total_started = time.perf_counter()
        effective_top_k = top_k or self._retrieval.default_top_k

        retrieval_started = time.perf_counter()
        execution = await execute_retrieval(
            retrieval=self._retrieval,
            rerank_service=self._rerank_service,
            query=query,
            top_k=effective_top_k,
            mode=mode,
            rerank=rerank,
            candidate_k=candidate_k,
            document_id=document_id,
        )
        retrieval_ms = (time.perf_counter() - retrieval_started) * 1000

        if not execution.hits:
            return self._insufficient_response(
                reason="知识库检索没有返回可用证据。",
                execution=execution,
                retrieval_count=0,
                latency=RagLatencyResponse(
                    retrieval_ms=retrieval_ms,
                    context_ms=0.0,
                    generation_ms=0.0,
                    total_ms=(time.perf_counter() - total_started) * 1000,
                ),
            )

        context_started = time.perf_counter()
        evidence = self._context_builder.build(execution.hits)
        context_ms = (time.perf_counter() - context_started) * 1000
        if not evidence.sources:
            return self._insufficient_response(
                reason="检索内容超出上下文 Token 预算，未形成可用证据。",
                execution=execution,
                retrieval_count=len(execution.hits),
                latency=RagLatencyResponse(
                    retrieval_ms=retrieval_ms,
                    context_ms=context_ms,
                    generation_ms=0.0,
                    total_ms=(time.perf_counter() - total_started) * 1000,
                ),
            )

        user_message = (
            "<question>\n"
            f"{query}\n"
            "</question>\n\n"
            "<knowledge_evidence>\n"
            f"{evidence.text}\n"
            "</knowledge_evidence>"
        )
        generation_started = time.perf_counter()
        result = await self._llm.generate(
            system_prompt=self._system_prompt,
            user_message=user_message,
        )
        generation_ms = (time.perf_counter() - generation_started) * 1000
        total_ms = (time.perf_counter() - total_started) * 1000

        payload = self._parse_model_payload(result.content)
        if payload is None:
            return self._invalid_generation_response(
                execution=execution,
                retrieval_count=len(execution.hits),
                model=result.model,
                usage=result,
                reason="模型未返回可解析的结构化答案。",
                retrieval_ms=retrieval_ms,
                context_ms=context_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
            )

        if payload.status == "insufficient_evidence":
            return self._insufficient_response(
                reason=payload.evidence_assessment
                or "模型判断现有证据不足以回答。",
                execution=execution,
                retrieval_count=len(execution.hits),
                model=result.model,
                usage=TokenUsage(
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                ),
                latency=RagLatencyResponse(
                    retrieval_ms=retrieval_ms,
                    context_ms=context_ms,
                    generation_ms=generation_ms,
                    total_ms=total_ms,
                ),
            )

        citation_error = self._validate_citations(
            payload,
            available_ids={source.citation_id for source in evidence.sources},
        )
        if citation_error is not None:
            logger.warning(
                "RAG citation validation failed reason=%s retrieval_count=%d",
                citation_error,
                len(execution.hits),
            )
            return self._invalid_generation_response(
                execution=execution,
                retrieval_count=len(execution.hits),
                model=result.model,
                usage=result,
                reason=citation_error,
                retrieval_ms=retrieval_ms,
                context_ms=context_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
            )

        used_ids = set(payload.used_citations)
        sources = [
            RagSourceResponse(
                citation_id=source.citation_id,
                document_id=source.hit.unit.document_id,
                chunk_id=source.hit.unit.chunk_id,
                filename=source.hit.unit.filename,
                page_number=source.hit.unit.page_number,
                part_index=source.hit.unit.part_index,
                content_excerpt=source.hit.unit.content[
                    : self._source_summary_chars
                ],
            )
            for source in evidence.sources
            if source.citation_id in used_ids
        ]
        logger.info(
            "RAG answer completed status=answered retrieval_count=%d citations=%d",
            len(execution.hits),
            len(sources),
        )
        return RagAskResponse(
            answer=payload.answer.strip(),
            status="answered",
            reason=payload.evidence_assessment or None,
            sources=sources,
            retrieval_mode=execution.mode,
            rerank_applied=execution.rerank_applied,
            retrieval_count=len(execution.hits),
            model=result.model,
            usage=TokenUsage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            ),
            latency_ms=RagLatencyResponse(
                retrieval_ms=retrieval_ms,
                context_ms=context_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
            ),
        )

    @staticmethod
    def _parse_model_payload(content: str) -> _ModelAnswerPayload | None:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            return _ModelAnswerPayload.model_validate(
                json.loads(text[start : end + 1])
            )
        except (json.JSONDecodeError, ValidationError):
            return None

    @staticmethod
    def _validate_citations(
        payload: _ModelAnswerPayload,
        *,
        available_ids: set[int],
    ) -> str | None:
        answer = payload.answer.strip()
        if not answer:
            return "模型标记为已回答，但回答正文为空。"
        used_ids = set(payload.used_citations)
        if not used_ids:
            return "模型标记为已回答，但没有返回引用编号。"
        if not used_ids.issubset(available_ids):
            return "模型引用了不存在的来源编号。"
        markers = {
            int(match.group(1))
            for match in _CITATION_PATTERN.finditer(answer)
        }
        if not markers:
            return "回答正文没有包含引用编号。"
        if not markers.issubset(available_ids):
            return "回答正文包含不存在的引用编号。"
        if markers != used_ids:
            return "回答正文引用编号与 used_citations 不一致。"
        return None

    def _insufficient_response(
        self,
        *,
        reason: str,
        execution,
        retrieval_count: int,
        latency: RagLatencyResponse,
        model: str | None = None,
        usage=None,
    ) -> RagAskResponse:
        logger.info(
            "RAG answer status=insufficient_evidence retrieval_count=%d",
            retrieval_count,
        )
        return RagAskResponse(
            answer=None,
            status="insufficient_evidence",
            reason=reason,
            sources=[],
            retrieval_mode=execution.mode,
            rerank_applied=execution.rerank_applied,
            retrieval_count=retrieval_count,
            model=model,
            usage=usage,
            latency_ms=latency,
        )

    def _invalid_generation_response(
        self,
        *,
        execution,
        retrieval_count: int,
        model: str,
        usage,
        reason: str,
        retrieval_ms: float,
        context_ms: float,
        generation_ms: float,
        total_ms: float,
    ) -> RagAskResponse:
        return self._insufficient_response(
            reason=reason,
            execution=execution,
            retrieval_count=retrieval_count,
            model=model,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
            ),
            latency=RagLatencyResponse(
                retrieval_ms=retrieval_ms,
                context_ms=context_ms,
                generation_ms=generation_ms,
                total_ms=total_ms,
            ),
        )

