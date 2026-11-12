"""Ticket-draft domain errors."""

from app.core.exceptions import ApplicationError


class TicketDraftValidationError(ApplicationError):
    def __init__(
        self,
        message: str,
        *,
        missing_fields: list[str] | None = None,
    ) -> None:
        super().__init__(
            message,
            code="TICKET_DRAFT_VALIDATION_ERROR",
            status_code=422,
        )
        self.missing_fields = missing_fields or []


class TicketDraftNotFoundError(ApplicationError):
    def __init__(self, draft_id: str) -> None:
        super().__init__(
            f"Ticket draft '{draft_id}' was not found.",
            code="TICKET_DRAFT_NOT_FOUND",
            status_code=404,
        )


class TicketPersistenceError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "The ticket draft could not be persisted.",
            code="TICKET_PERSISTENCE_ERROR",
            status_code=500,
        )

