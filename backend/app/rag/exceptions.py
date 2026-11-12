"""Errors raised while validating, parsing, and storing documents."""

from app.core.exceptions import ApplicationError


class DocumentValidationError(ApplicationError):
    """Raised when an uploaded document fails validation."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="DOCUMENT_VALIDATION_ERROR",
            status_code=400,
        )


class UnsupportedDocumentTypeError(ApplicationError):
    """Raised for file extensions outside the supported set."""

    def __init__(self, extension: str) -> None:
        super().__init__(
            f"Unsupported document type: {extension or 'unknown'}.",
            code="UNSUPPORTED_DOCUMENT_TYPE",
            status_code=415,
        )


class DocumentTooLargeError(ApplicationError):
    """Raised when an upload exceeds the configured size limit."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            f"Document exceeds the {max_bytes} byte upload limit.",
            code="DOCUMENT_TOO_LARGE",
            status_code=413,
        )


class DocumentParseError(ApplicationError):
    """Raised when text cannot be extracted from a valid file upload."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="DOCUMENT_PARSE_ERROR",
            status_code=422,
        )


class DocumentNotFoundError(ApplicationError):
    """Raised when a requested document does not exist."""

    def __init__(self, document_id: str) -> None:
        super().__init__(
            f"Document '{document_id}' was not found.",
            code="DOCUMENT_NOT_FOUND",
            status_code=404,
        )


class DocumentStorageError(ApplicationError):
    """Raised when local document persistence fails."""

    def __init__(self, message: str = "Could not persist the document.") -> None:
        super().__init__(
            message,
            code="DOCUMENT_STORAGE_ERROR",
            status_code=500,
        )


class EmbeddingUnavailableError(ApplicationError):
    """Raised when the embedding model cannot be loaded or executed."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="EMBEDDING_UNAVAILABLE",
            status_code=503,
        )


class EmbeddingDimensionError(ApplicationError):
    """Raised when generated vectors do not match the index dimension."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Embedding dimension mismatch: expected {expected}, got {actual}.",
            code="EMBEDDING_DIMENSION_MISMATCH",
            status_code=500,
        )


class QueryTokenLimitError(ApplicationError):
    """Raised when a search query exceeds the embedding model limit."""

    def __init__(self, actual: int, maximum: int) -> None:
        super().__init__(
            f"Query uses {actual} tokens and exceeds the {maximum} token limit.",
            code="QUERY_TOKEN_LIMIT_EXCEEDED",
            status_code=422,
        )


class EmbeddingTokenLimitError(ApplicationError):
    """Raised when a Chunk part still exceeds the embedding token limit."""

    def __init__(self, actual: int, maximum: int) -> None:
        super().__init__(
            f"Embedding input uses {actual} tokens and exceeds the "
            f"{maximum} token limit.",
            code="EMBEDDING_TOKEN_LIMIT_EXCEEDED",
            status_code=422,
        )


class VectorStoreUnavailableError(ApplicationError):
    """Raised when the local vector store cannot be opened."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="VECTOR_STORE_UNAVAILABLE",
            status_code=503,
        )


class IndexIncompatibleError(ApplicationError):
    """Raised when model, dimension, or index version differ."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="INDEX_INCOMPATIBLE",
            status_code=409,
        )


class DocumentNotIndexedError(ApplicationError):
    """Raised when a document has no vectors in the active index."""

    def __init__(self, document_id: str | None = None) -> None:
        target = f"Document '{document_id}'" if document_id else "Knowledge base"
        super().__init__(
            f"{target} has no vector index. Index the document before searching.",
            code="DOCUMENT_NOT_INDEXED",
            status_code=409,
        )


class InvalidRetrievalParameterError(ApplicationError):
    """Raised when a retrieval parameter is outside configured bounds."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="INVALID_RETRIEVAL_PARAMETER",
            status_code=422,
        )


class RerankerUnavailableError(ApplicationError):
    """Raised when reranking is disabled or the model cannot be loaded."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="RERANKER_UNAVAILABLE",
            status_code=503,
        )


class RerankerInputError(ApplicationError):
    """Raised when a query cannot be safely paired with candidate content."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="RERANKER_INPUT_ERROR",
            status_code=422,
        )


class AgentNodeExecutionError(ApplicationError):
    """Raised when an Agent graph node fails unexpectedly."""

    def __init__(self, node: str) -> None:
        super().__init__(
            f"The agent workflow failed while executing the {node} node.",
            code="AGENT_NODE_ERROR",
            status_code=500,
        )


