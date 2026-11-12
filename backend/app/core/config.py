"""Environment-backed application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and backend/.env."""

    app_name: str = "OpsPilot API"
    app_env: str = "development"
    log_level: str = "INFO"

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = Field(default=30.0, gt=0)
    deepseek_max_retries: int = Field(default=1, ge=0, le=5)

    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    document_storage_dir: Path = PROJECT_DIR / "storage" / "documents"
    document_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        le=100 * 1024 * 1024,
    )
    rag_chunk_size: int = Field(default=800, ge=100, le=10_000)
    rag_chunk_overlap: int = Field(default=120, ge=0, le=2_000)

    model_cache_dir: Path = PROJECT_DIR / "storage" / "models"
    embedding_model_name: str = "BAAI/bge-small-zh-v1.5"
    embedding_batch_size: int = Field(default=16, ge=1, le=128)
    embedding_max_tokens: int = Field(default=512, ge=64, le=8_192)
    embedding_overlap_tokens: int = Field(default=64, ge=0, le=1_024)
    embedding_query_instruction: str = (
        "为这个句子生成表示以用于检索相关文章："
    )
    qdrant_storage_dir: Path = PROJECT_DIR / "storage" / "qdrant"
    rag_index_version: int = Field(default=1, ge=1)
    rag_retrieval_default_top_k: int = Field(default=5, ge=1, le=100)
    rag_retrieval_max_top_k: int = Field(default=20, ge=1, le=100)
    bm25_storage_dir: Path = PROJECT_DIR / "storage" / "bm25"
    bm25_k1: float = Field(default=1.5, gt=0.0, le=10.0)
    bm25_b: float = Field(default=0.75, ge=0.0, le=1.0)
    rag_rrf_k: int = Field(default=60, ge=1, le=1_000)
    rag_rrf_candidate_k: int = Field(default=20, ge=1, le=100)
    reranker_enabled: bool = True
    reranker_model_name: str = "BAAI/bge-reranker-base"
    reranker_batch_size: int = Field(default=8, ge=1, le=64)
    reranker_max_length: int = Field(default=512, ge=64, le=2_048)
    reranker_overlap_tokens: int = Field(default=32, ge=0, le=256)
    reranker_candidate_k: int = Field(default=20, ge=1, le=100)
    rag_context_max_tokens: int = Field(default=3_000, ge=256, le=32_000)
    rag_source_summary_chars: int = Field(default=320, ge=80, le=2_000)
    agent_max_execution_steps: int = Field(default=10, ge=2, le=30)
    agent_max_tool_calls: int = Field(default=3, ge=1, le=10)
    ticket_database_path: Path = PROJECT_DIR / "storage" / "tickets.db"
    approval_checkpoint_path: Path = (
        PROJECT_DIR / "storage" / "approval_checkpoints.db"
    )

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_chunk_configuration(self) -> "Settings":
        if self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE")
        if self.embedding_overlap_tokens >= self.embedding_max_tokens:
            raise ValueError(
                "EMBEDDING_OVERLAP_TOKENS must be smaller than "
                "EMBEDDING_MAX_TOKENS"
            )
        if self.rag_retrieval_default_top_k > self.rag_retrieval_max_top_k:
            raise ValueError(
                "RAG_RETRIEVAL_DEFAULT_TOP_K must not exceed "
                "RAG_RETRIEVAL_MAX_TOP_K"
            )
        if self.rag_rrf_candidate_k > self.rag_retrieval_max_top_k:
            raise ValueError(
                "RAG_RRF_CANDIDATE_K must not exceed "
                "RAG_RETRIEVAL_MAX_TOP_K"
            )
        if self.reranker_overlap_tokens >= self.reranker_max_length:
            raise ValueError(
                "RERANKER_OVERLAP_TOKENS must be smaller than "
                "RERANKER_MAX_LENGTH"
            )
        if self.reranker_candidate_k > self.rag_retrieval_max_top_k:
            raise ValueError(
                "RERANKER_CANDIDATE_K must not exceed "
                "RAG_RETRIEVAL_MAX_TOP_K"
            )
        return self

    @property
    def resolved_document_storage_dir(self) -> Path:
        """Resolve relative storage paths against the project root."""
        if self.document_storage_dir.is_absolute():
            return self.document_storage_dir
        return PROJECT_DIR / self.document_storage_dir

    @property
    def resolved_model_cache_dir(self) -> Path:
        if self.model_cache_dir.is_absolute():
            return self.model_cache_dir
        return PROJECT_DIR / self.model_cache_dir

    @property
    def resolved_qdrant_storage_dir(self) -> Path:
        if self.qdrant_storage_dir.is_absolute():
            return self.qdrant_storage_dir
        return PROJECT_DIR / self.qdrant_storage_dir

    @property
    def resolved_bm25_storage_dir(self) -> Path:
        if self.bm25_storage_dir.is_absolute():
            return self.bm25_storage_dir
        return PROJECT_DIR / self.bm25_storage_dir

    @property
    def resolved_ticket_database_path(self) -> Path:
        if self.ticket_database_path.is_absolute():
            return self.ticket_database_path
        return PROJECT_DIR / self.ticket_database_path

    @property
    def resolved_approval_checkpoint_path(self) -> Path:
        if self.approval_checkpoint_path.is_absolute():
            return self.approval_checkpoint_path
        return PROJECT_DIR / self.approval_checkpoint_path

    @property
    def ticket_database_url(self) -> str:
        return (
            "sqlite+aiosqlite:///"
            + self.resolved_ticket_database_path.as_posix()
        )


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()

