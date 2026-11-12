"""Local human-in-the-loop approval endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_approval_service, require_local_approval_access
from app.api.v1.tickets import approval_detail_response
from app.approvals.service import TicketApprovalService
from app.schemas.approval import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalDetailResponse,
    ApprovalRecordResponse,
)

router = APIRouter(
    prefix="/agent/approvals",
    tags=["approvals"],
    dependencies=[Depends(require_local_approval_access)],
)


@router.get("/{thread_id}", response_model=ApprovalDetailResponse)
async def get_approval(
    thread_id: str,
    service: Annotated[TicketApprovalService, Depends(get_approval_service)],
) -> ApprovalDetailResponse:
    """Return the persisted draft together with the live checkpoint state."""
    return approval_detail_response(await service.get(thread_id))


@router.post("/{thread_id}/decision", response_model=ApprovalDecisionResponse)
async def decide_approval(
    thread_id: str,
    payload: ApprovalDecisionRequest,
    service: Annotated[TicketApprovalService, Depends(get_approval_service)],
) -> ApprovalDecisionResponse:
    """Resume a genuinely interrupted graph with an approve/reject decision."""
    result = await service.decide(thread_id, payload)
    return ApprovalDecisionResponse(
        approval=ApprovalRecordResponse(
            thread_id=result.transition.approval.thread_id,
            draft_id=result.transition.approval.draft_id,
            draft_version=result.transition.approval.draft_version,
            status=result.transition.approval.status,
            note=result.transition.approval.note,
            requested_at=result.transition.approval.requested_at,
            decided_at=result.transition.approval.decided_at,
        ),
        draft=result.transition.draft,
        decision=result.decision,
        executed_nodes=result.executed_nodes,
    )
