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


class TicketDraftStateConflictError(ApplicationError):
    def __init__(self, draft_id: str) -> None:
        super().__init__(
            f"Ticket draft '{draft_id}' is not editable in its current state.",
            code="TICKET_DRAFT_STATE_CONFLICT",
            status_code=409,
        )


class TicketApprovalNotFoundError(ApplicationError):
    def __init__(self, thread_id: str) -> None:
        super().__init__(
            f"Ticket approval '{thread_id}' was not found.",
            code="TICKET_APPROVAL_NOT_FOUND",
            status_code=404,
        )


class TicketApprovalStateConflictError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="TICKET_APPROVAL_STATE_CONFLICT",
            status_code=409,
        )


class TicketDraftVersionConflictError(ApplicationError):
    def __init__(self, draft_id: str) -> None:
        super().__init__(
            (
                f"Ticket draft '{draft_id}' changed after approval was "
                "requested."
            ),
            code="TICKET_DRAFT_VERSION_CONFLICT",
            status_code=409,
        )


class ApprovalCheckpointStateError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="APPROVAL_CHECKPOINT_STATE_INVALID",
            status_code=409,
        )


class ApprovalWorkflowExecutionError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "The approval workflow could not continue.",
            code="APPROVAL_WORKFLOW_ERROR",
            status_code=500,
        )

