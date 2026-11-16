"""Conversation memory domain errors."""

from app.core.exceptions import ApplicationError


class ConversationNotFoundError(ApplicationError):
    def __init__(self, conversation_id: str) -> None:
        super().__init__(
            f"Conversation '{conversation_id}' was not found.",
            code="CONVERSATION_NOT_FOUND",
            status_code=404,
        )


class ConversationPersistenceError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "The conversation history could not be persisted.",
            code="CONVERSATION_PERSISTENCE_ERROR",
            status_code=500,
        )


class AgentIdempotencyConflictError(ApplicationError):
    """Raised when one idempotency key is reused for different request data."""

    def __init__(self) -> None:
        super().__init__(
            "The Idempotency-Key was already used for a different Agent request.",
            code="AGENT_IDEMPOTENCY_KEY_REUSED",
            status_code=409,
        )
