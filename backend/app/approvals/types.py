"""Domain records shared by approval persistence and graph nodes."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.schemas.ticket import TicketDraftResponse

ApprovalStatus = Literal["pending_approval", "approved", "rejected"]


@dataclass(frozen=True, slots=True)
class TicketApprovalRecord:
    thread_id: str
    draft_id: str
    draft_version: int
    status: ApprovalStatus
    note: str | None
    requested_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class TicketApprovalTransition:
    approval: TicketApprovalRecord
    draft: TicketDraftResponse
