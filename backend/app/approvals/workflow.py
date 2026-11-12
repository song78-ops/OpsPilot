"""Thin wrapper around the interruptible approval graph."""

import logging
from typing import Any

from langgraph.types import Command, StateSnapshot

from app.approvals.graph import build_approval_graph
from app.core.exceptions import ApplicationError
from app.schemas.approval import ApprovalDecisionRequest
from app.tickets.exceptions import (
    ApprovalCheckpointStateError,
    ApprovalWorkflowExecutionError,
)
from app.tickets.repository import TicketDraftRepository

logger = logging.getLogger(__name__)


class ApprovalWorkflow:
    """Start, inspect, and resume one approval graph execution."""

    def __init__(
        self,
        *,
        repository: TicketDraftRepository,
        checkpointer: Any,
        max_execution_steps: int = 6,
    ) -> None:
        self._graph = build_approval_graph(
            repository,
            checkpointer=checkpointer,
        )
        self._max_execution_steps = max_execution_steps

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self._max_execution_steps,
        }

    async def start(
        self,
        *,
        thread_id: str,
        draft_id: str,
    ) -> StateSnapshot:
        try:
            await self._graph.ainvoke(
                {
                    "thread_id": thread_id,
                    "draft_id": draft_id,
                    "executed_nodes": [],
                },
                self._config(thread_id),
                durability="sync",
            )
        except ApplicationError:
            raise
        except Exception as exc:
            logger.error(
                "Approval graph start failed type=%s",
                type(exc).__name__,
            )
            raise ApprovalWorkflowExecutionError() from exc
        snapshot = await self.get_snapshot(thread_id)
        if not self._is_waiting(snapshot):
            raise ApprovalCheckpointStateError(
                "Approval workflow did not reach a real interrupt."
            )
        return snapshot

    async def resume(
        self,
        *,
        thread_id: str,
        decision: ApprovalDecisionRequest,
    ) -> StateSnapshot:
        try:
            await self._graph.ainvoke(
                Command(resume=decision.model_dump(mode="json")),
                self._config(thread_id),
                durability="sync",
            )
        except ApplicationError:
            raise
        except Exception as exc:
            logger.error(
                "Approval graph resume failed type=%s",
                type(exc).__name__,
            )
            raise ApprovalWorkflowExecutionError() from exc
        snapshot = await self.get_snapshot(thread_id)
        if snapshot.interrupts or snapshot.next:
            raise ApprovalCheckpointStateError(
                "Approval workflow is still paused after the decision."
            )
        return snapshot

    async def retry_pending_task(self, thread_id: str) -> StateSnapshot:
        """Retry a failed post-interrupt task without replaying the interrupt."""
        try:
            await self._graph.ainvoke(
                None,
                self._config(thread_id),
                durability="sync",
            )
        except ApplicationError:
            raise
        except Exception as exc:
            logger.error(
                "Approval graph retry failed type=%s",
                type(exc).__name__,
            )
            raise ApprovalWorkflowExecutionError() from exc
        snapshot = await self.get_snapshot(thread_id)
        if snapshot.interrupts or snapshot.next:
            raise ApprovalCheckpointStateError(
                "Approval workflow is still paused after retrying."
            )
        return snapshot

    async def get_snapshot(self, thread_id: str) -> StateSnapshot:
        try:
            return await self._graph.aget_state(self._config(thread_id))
        except Exception as exc:
            logger.error(
                "Approval checkpoint read failed type=%s",
                type(exc).__name__,
            )
            raise ApprovalWorkflowExecutionError() from exc

    async def delete_thread(self, thread_id: str) -> None:
        """Remove a just-created checkpoint when DB registration fails."""
        try:
            await self._graph.checkpointer.adelete_thread(thread_id)
        except Exception:
            logger.exception(
                "Failed to delete orphan approval checkpoint thread=%s",
                thread_id,
            )

    @staticmethod
    def _is_waiting(snapshot: StateSnapshot) -> bool:
        return bool(snapshot.interrupts) and any(
            task.name == "await_decision" and bool(task.interrupts)
            for task in snapshot.tasks
        )

    @staticmethod
    def _is_retryable_after_error(snapshot: StateSnapshot) -> bool:
        return (
            not snapshot.interrupts
            and snapshot.next == ("apply_decision",)
            and any(
                task.name == "apply_decision" and task.error is not None
                for task in snapshot.tasks
            )
        )
