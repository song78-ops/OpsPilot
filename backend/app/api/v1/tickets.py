"""Persisted ticket draft query and update endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_approval_service,
    get_ticket_service,
    require_local_approval_access,
)
from app.approvals.service import ApprovalView, TicketApprovalService
from app.schemas.approval import ApprovalDetailResponse, ApprovalRecordResponse
from app.schemas.ticket import (
    TicketDraftListResponse,
    TicketDraftResponse,
    TicketDraftUpdateRequest,
)
from app.tickets.service import TicketDraftService

router = APIRouter(prefix="/tickets/drafts", tags=["tickets"])


def approval_detail_response(view: ApprovalView) -> ApprovalDetailResponse:
    return ApprovalDetailResponse(
        approval=ApprovalRecordResponse(
            thread_id=view.approval.thread_id,
            draft_id=view.approval.draft_id,
            draft_version=view.approval.draft_version,
            status=view.approval.status,
            note=view.approval.note,
            requested_at=view.approval.requested_at,
            decided_at=view.approval.decided_at,
        ),
        draft=view.draft,
        waiting_for_decision=view.waiting_for_decision,
        checkpoint_next=view.checkpoint_next,
    )


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


@router.post(
    "/{draft_id}/request-approval",
    response_model=ApprovalDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_local_approval_access)],
)
async def request_ticket_draft_approval(
    draft_id: str,
    service: Annotated[TicketApprovalService, Depends(get_approval_service)],
) -> ApprovalDetailResponse:
    """Pause a real LangGraph thread until a local human decision arrives."""
    return approval_detail_response(await service.request(draft_id))

