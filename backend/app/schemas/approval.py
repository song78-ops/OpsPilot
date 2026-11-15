"""Human approval request and response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.ticket import TicketDraftResponse

ApprovalStatus = Literal["pending_approval", "approved", "rejected"]
ApprovalDecision = Literal["approve", "reject"]
DraftApprovalStatus = Literal[
    "not_requested",
    "pending_approval",
    "approved",
    "rejected",
]


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ApprovalRecordResponse(BaseModel):
    thread_id: str
    draft_id: str
    draft_version: int
    status: ApprovalStatus
    note: str | None
    requested_at: datetime
    decided_at: datetime | None


class ApprovalDetailResponse(BaseModel):
    approval: ApprovalRecordResponse
    draft: TicketDraftResponse
    waiting_for_decision: bool
    checkpoint_next: list[str]


class DraftApprovalLookupResponse(BaseModel):
    draft: TicketDraftResponse
    approval: ApprovalRecordResponse | None
    status: DraftApprovalStatus
    waiting_for_decision: bool
    checkpoint_next: list[str]


class ApprovalDecisionResponse(BaseModel):
    approval: ApprovalRecordResponse
    draft: TicketDraftResponse
    decision: ApprovalDecision
    executed_nodes: list[str]
    waiting_for_decision: Literal[False] = False
