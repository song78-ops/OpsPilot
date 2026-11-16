"""FastAPI dependency providers."""

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from app.agents.nodes import AgentNodes
from app.agents.service import AgentService
from app.agents.workflow import AgentWorkflow
from app.approvals.service import TicketApprovalService
from app.conversations.repository import (
    ConversationRepository,
    SQLAlchemyConversationRepository,
)
from app.conversations.service import ConversationMemoryService
from app.core.config import Settings, get_settings
from app.core.exceptions import ApplicationError, ConfigurationError
from app.llm.base import LLMProvider
from app.llm.deepseek import DeepSeekLLM
from app.rag.service import DocumentService
from app.rag.embeddings.bge import BgeEmbeddingModel
from app.rag.retrieval.bm25 import BM25IndexStore
from app.rag.retrieval.hybrid import HybridRetrievalService
from app.rag.retrieval.qdrant import QdrantVectorStore
from app.rag.retrieval.service import DenseRetrievalService
from app.rag.qa.context import EvidenceContextBuilder
from app.rag.qa.service import RagQAService
from app.rag.reranking.bge import BgeCrossEncoderReranker
from app.rag.reranking.service import RerankService
from app.rag.storage.local import LocalDocumentStore
from app.services.chat_service import ChatService
from app.tickets.repository import (
    SQLAlchemyTicketDraftRepository,
    TicketDraftRepository,
)
from app.tickets.service import TicketDraftService
from app.tools.ticket_tools import TicketToolExecutor

SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1] / "prompts" / "system" / "chat_system.txt"
)
RAG_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "system"
    / "rag_answer_system.txt"
)
SUPERVISOR_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "system"
    / "supervisor.txt"
)
TICKET_DRAFT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "system"
    / "ticket_draft.txt"
)
_ACTIVE_VECTOR_STORES: list[QdrantVectorStore] = []
_ACTIVE_TICKET_REPOSITORIES: list[SQLAlchemyTicketDraftRepository] = []
_ACTIVE_CONVERSATION_REPOSITORIES: list[
    SQLAlchemyConversationRepository
] = []


async def get_llm_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[LLMProvider]:
    """Create a scoped DeepSeek client and close it after the request."""
    if settings.deepseek_api_key is None or not (
        settings.deepseek_api_key.get_secret_value().strip()
    ):
        raise ConfigurationError(
            "DEEPSEEK_API_KEY is not configured. Add it to backend/.env."
        )

    client = DeepSeekLLM(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        max_retries=settings.deepseek_max_retries,
        temperature=settings.llm_temperature,
    )
    try:
        yield client
    finally:
        await client.aclose()


def get_chat_service(
    llm: Annotated[LLMProvider, Depends(get_llm_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatService:
    """Build the chat use case with its model dependency."""
    return ChatService(
        llm=llm,
        system_prompt=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip(),
        model_name=settings.deepseek_model,
        stream_idle_timeout_seconds=(
            settings.deepseek_timeout_seconds + 5
        ),
    )


def get_document_service(
    settings: Annotated[Settings, Depends(get_settings)],
) -> DocumentService:
    """Build a local document ingestion service from runtime settings."""
    return DocumentService(
        store=LocalDocumentStore(settings.resolved_document_storage_dir),
        max_upload_bytes=settings.document_max_upload_bytes,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )


@lru_cache
def _build_embedding_model(
    model_name: str,
    cache_dir: str,
    batch_size: int,
    max_tokens: int,
    overlap_tokens: int,
    query_instruction: str,
) -> BgeEmbeddingModel:
    return BgeEmbeddingModel(
        model_name=model_name,
        cache_dir=Path(cache_dir),
        batch_size=batch_size,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        query_instruction=query_instruction,
    )


def get_embedding_model(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BgeEmbeddingModel:
    """Return one lazy BGE model instance for the application process."""
    return _build_embedding_model(
        settings.embedding_model_name,
        str(settings.resolved_model_cache_dir),
        settings.embedding_batch_size,
        settings.embedding_max_tokens,
        settings.embedding_overlap_tokens,
        settings.embedding_query_instruction,
    )


@lru_cache
def _build_vector_store(
    storage_dir: str,
    model_name: str,
    dimension: int,
    index_version: int,
    query_instruction: str,
) -> QdrantVectorStore:
    vector_store = QdrantVectorStore(
        storage_dir=Path(storage_dir),
        model_name=model_name,
        dimension=dimension,
        index_version=index_version,
        query_instruction=query_instruction,
    )
    _ACTIVE_VECTOR_STORES.append(vector_store)
    return vector_store


def get_vector_store(
    settings: Annotated[Settings, Depends(get_settings)],
    embedding: Annotated[
        BgeEmbeddingModel,
        Depends(get_embedding_model),
    ],
) -> QdrantVectorStore:
    """Return one local Qdrant client for this application process."""
    model_info = embedding.info
    return _build_vector_store(
        str(settings.resolved_qdrant_storage_dir),
        model_info.name,
        model_info.dimension,
        settings.rag_index_version,
        model_info.query_instruction,
    )


def get_retrieval_service(
    document_service: Annotated[
        DocumentService,
        Depends(get_document_service),
    ],
    embedding: Annotated[
        BgeEmbeddingModel,
        Depends(get_embedding_model),
    ],
    vector_store: Annotated[
        QdrantVectorStore,
        Depends(get_vector_store),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HybridRetrievalService:
    dense_service = DenseRetrievalService(
        document_service=document_service,
        embedding=embedding,
        vector_store=vector_store,
        index_version=settings.rag_index_version,
        default_top_k=settings.rag_retrieval_default_top_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )
    bm25_store = _build_bm25_store(
        str(settings.resolved_bm25_storage_dir),
        embedding.info.name,
        settings.rag_index_version,
        settings.bm25_k1,
        settings.bm25_b,
    )
    return HybridRetrievalService(
        document_service=document_service,
        dense=dense_service,
        bm25=bm25_store,
        rrf_k=settings.rag_rrf_k,
        candidate_k=settings.rag_rrf_candidate_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )


@lru_cache
def _build_bm25_store(
    storage_dir: str,
    embedding_model: str,
    index_version: int,
    k1: float,
    b: float,
) -> BM25IndexStore:
    return BM25IndexStore(
        storage_dir=Path(storage_dir),
        embedding_model=embedding_model,
        index_version=index_version,
        k1=k1,
        b=b,
    )


@lru_cache
def _build_reranker(
    model_name: str,
    cache_dir: str,
    batch_size: int,
    max_length: int,
    overlap_tokens: int,
) -> BgeCrossEncoderReranker:
    return BgeCrossEncoderReranker(
        model_name=model_name,
        cache_dir=Path(cache_dir),
        batch_size=batch_size,
        max_length=max_length,
        overlap_tokens=overlap_tokens,
    )


def get_reranker(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BgeCrossEncoderReranker | None:
    """Return one lazy CPU reranker, or None when disabled by configuration."""
    if not settings.reranker_enabled:
        return None
    return _build_reranker(
        settings.reranker_model_name,
        str(settings.resolved_model_cache_dir),
        settings.reranker_batch_size,
        settings.reranker_max_length,
        settings.reranker_overlap_tokens,
    )


def get_rerank_service(
    reranker: Annotated[
        BgeCrossEncoderReranker | None,
        Depends(get_reranker),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RerankService:
    return RerankService(
        reranker=reranker,
        default_candidate_k=settings.reranker_candidate_k,
        max_top_k=settings.rag_retrieval_max_top_k,
    )


def get_rag_qa_service(
    llm: Annotated[LLMProvider, Depends(get_llm_client)],
    embedding: Annotated[
        BgeEmbeddingModel,
        Depends(get_embedding_model),
    ],
    retrieval: Annotated[
        HybridRetrievalService,
        Depends(get_retrieval_service),
    ],
    rerank_service: Annotated[
        RerankService,
        Depends(get_rerank_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RagQAService:
    return RagQAService(
        retrieval=retrieval,
        rerank_service=rerank_service,
        llm=llm,
        system_prompt=RAG_SYSTEM_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        context_builder=EvidenceContextBuilder(
            max_tokens=settings.rag_context_max_tokens,
            count_tokens=embedding.count_tokens,
        ),
        source_summary_chars=settings.rag_source_summary_chars,
    )


@lru_cache
def _build_ticket_repository(
    database_url: str,
) -> SQLAlchemyTicketDraftRepository:
    repository = SQLAlchemyTicketDraftRepository(database_url)
    _ACTIVE_TICKET_REPOSITORIES.append(repository)
    return repository


def get_ticket_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SQLAlchemyTicketDraftRepository:
    return _build_ticket_repository(settings.ticket_database_url)


def get_ticket_service(
    repository: Annotated[
        TicketDraftRepository,
        Depends(get_ticket_repository),
    ],
) -> TicketDraftService:
    return TicketDraftService(repository)


def get_ticket_tool_executor(
    service: Annotated[TicketDraftService, Depends(get_ticket_service)],
) -> TicketToolExecutor:
    return TicketToolExecutor(service)


@lru_cache
def _build_conversation_repository(
    database_url: str,
) -> SQLAlchemyConversationRepository:
    repository = SQLAlchemyConversationRepository(database_url)
    _ACTIVE_CONVERSATION_REPOSITORIES.append(repository)
    return repository


def get_conversation_repository(
    settings: Annotated[Settings, Depends(get_settings)],
) -> SQLAlchemyConversationRepository:
    return _build_conversation_repository(
        settings.conversation_database_url
    )


def get_conversation_memory_service(
    repository: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
    ticket_service: Annotated[
        TicketDraftService,
        Depends(get_ticket_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ConversationMemoryService:
    return ConversationMemoryService(
        repository=repository,
        ticket_service=ticket_service,
        max_history_messages=settings.agent_history_max_messages,
        history_token_budget=settings.agent_history_token_budget,
    )


def get_approval_service(request: Request) -> TicketApprovalService:
    """Return the lifespan-owned approval service."""
    service = getattr(request.app.state, "approval_service", None)
    if not isinstance(service, TicketApprovalService):
        raise ConfigurationError(
            "The approval workflow is not initialized for this application."
        )
    return service


def require_local_approval_access(request: Request) -> None:
    """Keep the unauthenticated demo approval API on the local machine."""
    host = request.client.host if request.client is not None else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise ApplicationError(
            "The demo approval API is available from localhost only.",
            code="APPROVAL_LOCAL_ONLY",
            status_code=403,
        )


def require_local_agent_access(request: Request) -> None:
    """Protect unauthenticated Agent history and ticket references."""
    host = request.client.host if request.client is not None else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise ApplicationError(
            "The demo Agent API is available from localhost only.",
            code="AGENT_LOCAL_ONLY",
            status_code=403,
        )


async def close_application_resources() -> None:
    """Close local vector stores and SQLite engines before process exit."""
    for vector_store in _ACTIVE_VECTOR_STORES:
        vector_store.close()
    _ACTIVE_VECTOR_STORES.clear()
    _build_vector_store.cache_clear()
    for repository in _ACTIVE_TICKET_REPOSITORIES:
        await repository.close()
    _ACTIVE_TICKET_REPOSITORIES.clear()
    _build_ticket_repository.cache_clear()
    for repository in _ACTIVE_CONVERSATION_REPOSITORIES:
        await repository.close()
    _ACTIVE_CONVERSATION_REPOSITORIES.clear()
    _build_conversation_repository.cache_clear()


def get_agent_service(
    llm: Annotated[LLMProvider, Depends(get_llm_client)],
    rag_service: Annotated[
        RagQAService,
        Depends(get_rag_qa_service),
    ],
    chat_service: Annotated[
        ChatService,
        Depends(get_chat_service),
    ],
    ticket_tool_executor: Annotated[
        TicketToolExecutor,
        Depends(get_ticket_tool_executor),
    ],
    conversation_memory: Annotated[
        ConversationMemoryService,
        Depends(get_conversation_memory_service),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AgentService:
    nodes = AgentNodes(
        llm=llm,
        rag_service=rag_service,
        chat_service=chat_service,
        ticket_tool_executor=ticket_tool_executor,
        supervisor_prompt=SUPERVISOR_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        ticket_prompt=TICKET_DRAFT_PROMPT_PATH.read_text(
            encoding="utf-8"
        ).strip(),
        max_tool_calls=settings.agent_max_tool_calls,
    )
    workflow = AgentWorkflow(
        nodes=nodes,
        max_execution_steps=settings.agent_max_execution_steps,
    )
    return AgentService(
        workflow=workflow,
        conversation_memory=conversation_memory,
    )

