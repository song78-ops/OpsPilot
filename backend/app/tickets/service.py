"""Validated ticket-draft business operations."""

from app.schemas.ticket import (
    CreateTicketDraftArgs,
    TicketDraftResponse,
    TicketDraftUpdateRequest,
)
from app.tickets.exceptions import (
    TicketDraftNotFoundError,
    TicketDraftValidationError,
)
from app.tickets.repository import (
    TicketDraftMutation,
    TicketDraftRepository,
    TicketDraftWrite,
)


class TicketDraftService:
    """Save only validated drafts; never create a formal ticket."""

    def __init__(self, repository: TicketDraftRepository) -> None:
        self._repository = repository

    async def create(
        self,
        *,
        args: CreateTicketDraftArgs,
        idempotency_key: str,
    ) -> TicketDraftWrite:
        title = args.title.strip()
        description = args.description.strip()
        device = args.device_or_system.strip()
        missing = [
            name
            for name, value in (
                ("title", title),
                ("description", description),
                ("device_or_system", device),
            )
            if not value
        ]
        if missing:
            raise TicketDraftValidationError(
                "Missing required ticket draft fields: " + ", ".join(missing),
                missing_fields=missing,
            )
        return await self._repository.create(
            idempotency_key=idempotency_key,
            title=title,
            description=description,
            device_or_system=device,
        )

    async def get(self, draft_id: str) -> TicketDraftResponse:
        draft = await self._repository.get(draft_id)
        if draft is None:
            raise TicketDraftNotFoundError(draft_id)
        return draft

    async def update(
        self,
        draft_id: str,
        values: TicketDraftUpdateRequest,
    ) -> TicketDraftResponse:
        normalized = self._normalize_update(values)
        draft = await self._repository.update(draft_id, normalized)
        if draft is None:
            raise TicketDraftNotFoundError(draft_id)
        return draft

    async def update_with_idempotency(
        self,
        draft_id: str,
        values: TicketDraftUpdateRequest,
        *,
        idempotency_key: str,
    ) -> TicketDraftMutation:
        normalized = self._normalize_update(values)
        return await self._repository.update_with_idempotency(
            idempotency_key=idempotency_key,
            draft_id=draft_id,
            values=normalized,
        )

    @staticmethod
    def _normalize_update(
        values: TicketDraftUpdateRequest,
    ) -> TicketDraftUpdateRequest:
        normalized = TicketDraftUpdateRequest(
            title=values.title.strip() if values.title is not None else None,
            description=(
                values.description.strip()
                if values.description is not None
                else None
            ),
            device_or_system=(
                values.device_or_system.strip()
                if values.device_or_system is not None
                else None
            ),
        )
        if any(
            value == ""
            for value in (
                normalized.title,
                normalized.description,
                normalized.device_or_system,
            )
            if value is not None
        ):
            raise TicketDraftValidationError(
                "Updated ticket draft fields must not be blank."
            )
        return normalized

    async def list(self) -> list[TicketDraftResponse]:
        return await self._repository.list()

