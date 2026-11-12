"""Application orchestration for ticket approval state transitions."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.approvals.types import (
    TicketApprovalRecord,
    TicketApprovalTransition,
)
from app.approvals.workflow import ApprovalWorkflow
from app.core.exceptions import ApplicationError
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.ticket import TicketDraftResponse
from app.tickets.exceptions import (
    ApprovalCheckpointStateError,
    TicketApprovalNotFoundError,
    TicketApprovalStateConflictError,
    TicketDraftNotFoundError,
    TicketDraftStateConflictError,
    TicketDraftVersionConflictError,
)
from app.tickets.repository import TicketDraftRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovalView:
    approval: TicketApprovalRecord
    draft: TicketDraftResponse
    waiting_for_decision: bool
    checkpoint_next: list[str]


@dataclass(frozen=True, slots=True)
class ApprovalDecisionView:
    transition: TicketApprovalTransition
    decision: str
    executed_nodes: list[str]


class TicketApprovalService:
    """Coordinate real interrupts with transactional business transitions."""

    def __init__(
        self,
        *,
        repository: TicketDraftRepository,
        workflow: ApprovalWorkflow,
    ) -> None:
        self._repository = repository
        self._workflow = workflow
        self._thread_locks: dict[str, asyncio.Lock] = {}

    async def request(self, draft_id: str) -> ApprovalView:
        draft = await self._repository.get(draft_id)
        if draft is None:
            raise TicketDraftNotFoundError(draft_id)
        existing = await self._repository.get_approval_by_draft(draft_id)
        if existing is not None:
            raise TicketApprovalStateConflictError(
                f"Ticket draft '{draft_id}' already has an approval."
            )
        if draft.status != "draft":
            raise TicketDraftStateConflictError(draft_id)

        thread_id = uuid.uuid4().hex
        try:
            snapshot = await self._workflow.start(
                thread_id=thread_id,
                draft_id=draft_id,
            )
            expected_version = self._validate_snapshot_identity(
                snapshot.values,
                thread_id=thread_id,
                draft_id=draft_id,
            )
            transition = await self._repository.request_approval(
                draft_id=draft_id,
                thread_id=thread_id,
                expected_version=expected_version,
            )
        except BaseException:
            await self._workflow.delete_thread(thread_id)
            raise

        return ApprovalView(
            approval=transition.approval,
            draft=transition.draft,
            waiting_for_decision=True,
            checkpoint_next=list(snapshot.next),
        )

    async def get(self, thread_id: str) -> ApprovalView:
        approval = await self._repository.get_approval(thread_id)
        if approval is None:
            raise TicketApprovalNotFoundError(thread_id)
        snapshot = await self._workflow.get_snapshot(thread_id)
        self._validate_snapshot_identity(
            snapshot.values,
            thread_id=thread_id,
            draft_id=approval.draft_id,
        )
        waiting = ApprovalWorkflow._is_waiting(snapshot)
        if approval.status == "pending_approval" and not waiting:
            raise ApprovalCheckpointStateError(
                "Approval is marked pending but has no active interrupt."
            )
        if approval.status != "pending_approval" and waiting:
            raise ApprovalCheckpointStateError(
                "A completed approval still has an active interrupt."
            )
        draft = await self._repository.get(approval.draft_id)
        if draft is None:
            raise TicketDraftNotFoundError(approval.draft_id)
        return ApprovalView(
            approval=approval,
            draft=draft,
            waiting_for_decision=waiting,
            checkpoint_next=list(snapshot.next),
        )

    async def decide(
        self,
        thread_id: str,
        decision: ApprovalDecisionRequest,
    ) -> ApprovalDecisionView:
        lock = self._thread_locks.setdefault(thread_id, asyncio.Lock())
        async with lock:
            approval = await self._repository.get_approval(thread_id)
            if approval is None:
                raise TicketApprovalNotFoundError(thread_id)
            if approval.status != "pending_approval":
                raise TicketApprovalStateConflictError(
                    "Approval is no longer waiting for a decision."
                )
            snapshot = await self._workflow.get_snapshot(thread_id)
            self._validate_snapshot_identity(
                snapshot.values,
                thread_id=thread_id,
                draft_id=approval.draft_id,
            )
            retrying = ApprovalWorkflow._is_retryable_after_error(snapshot)
            if not ApprovalWorkflow._is_waiting(snapshot) and not retrying:
                raise ApprovalCheckpointStateError(
                    "Approval checkpoint is not paused at the decision node."
                )
            if retrying:
                resumed_decision = snapshot.values.get("decision")
                resumed_note = snapshot.values.get("decision_note")
                if (
                    resumed_decision != decision.decision
                    or resumed_note != decision.note
                ):
                    raise TicketApprovalStateConflictError(
                        "A different decision had already been submitted."
                    )
            draft = await self._repository.get(approval.draft_id)
            if draft is None:
                raise TicketDraftNotFoundError(approval.draft_id)
            if draft.status != "pending_approval":
                raise TicketApprovalStateConflictError(
                    "Ticket draft is not pending approval."
                )
            if draft.version != approval.draft_version:
                raise TicketDraftVersionConflictError(draft.id)

            try:
                if retrying:
                    final_snapshot = (
                        await self._workflow.retry_pending_task(thread_id)
                    )
                else:
                    final_snapshot = await self._workflow.resume(
                        thread_id=thread_id,
                        decision=decision,
                    )
            except ApplicationError:
                raise

            transition_approval = await self._repository.get_approval(thread_id)
            transition_draft = await self._repository.get(approval.draft_id)
            if transition_approval is None or transition_draft is None:
                raise ApprovalCheckpointStateError(
                    "Approval result was not persisted."
                )
            expected_status = (
                "approved" if decision.decision == "approve" else "rejected"
            )
            if (
                transition_approval.status != expected_status
                or transition_draft.status != expected_status
            ):
                raise ApprovalCheckpointStateError(
                    "Approval result does not match the persisted state."
                )
            executed_nodes = list(
                final_snapshot.values.get("executed_nodes", [])
            )
            return ApprovalDecisionView(
                transition=TicketApprovalTransition(
                    approval=transition_approval,
                    draft=transition_draft,
                ),
                decision=decision.decision,
                executed_nodes=executed_nodes,
            )

    @staticmethod
    def _validate_snapshot_identity(
        values: dict[str, Any],
        *,
        thread_id: str,
        draft_id: str,
    ) -> int:
        if (
            values.get("thread_id") != thread_id
            or values.get("draft_id") != draft_id
            or not isinstance(values.get("draft_version"), int)
        ):
            raise ApprovalCheckpointStateError(
                "Checkpoint data does not match the approval mapping."
            )
        return int(values["draft_version"])
