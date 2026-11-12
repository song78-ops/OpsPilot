"""Persisted ticket draft query and update endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_ticket_service
from app.schemas.ticket import (
    TicketDraftListResponse,
    TicketDraftResponse,
    TicketDraftUpdateRequest,
)
from app.tickets.service import TicketDraftService

router = APIRouter(prefix="/tickets/drafts", tags=["tickets"])


@router.get("", response_model=TicketDraftListResponse)
async def list_ticket_drafts(
    service: Annotated[TicketDraftService, Depends(get_ticket_service)],
) -> TicketDraftListResponse:
    drafts = await service.list()
    return TicketDraftListResponse(items=drafts, total=len(drafts))


@router.get("/{draft_id}", response_model=TicketDraftResponse)
async def get_ticket_draft(
    draft_id: str,
    service: Annotated[TicketDraftService, Depends(get_ticket_service)],
) -> TicketDraftResponse:
    return await service.get(draft_id)


@router.patch("/{draft_id}", response_model=TicketDraftResponse)
async def update_ticket_draft(
    draft_id: str,
    payload: TicketDraftUpdateRequest,
    service: Annotated[TicketDraftService, Depends(get_ticket_service)],
) -> TicketDraftResponse:
    return await service.update(draft_id, payload)

