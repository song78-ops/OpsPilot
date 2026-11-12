"""Independent LangGraph graph used only for ticket approval pauses."""

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.ticket import TicketDraftResponse
from app.tickets.exceptions import TicketDraftNotFoundError
from app.tickets.exceptions import TicketDraftStateConflictError
from app.tickets.repository import TicketDraftRepository


class ApprovalState(TypedDict, total=False):
    thread_id: str
    draft_id: str
    draft_version: int
    draft_snapshot: dict[str, Any]
    decision: str
    decision_note: str | None
    decision_result: dict[str, Any]
    executed_nodes: Annotated[list[str], operator.add]


class ApprovalGraphNodes:
    """Nodes that read the draft before interrupting and apply a decision."""

    def __init__(self, repository: TicketDraftRepository) -> None:
        self._repository = repository

    async def load_draft(self, state: ApprovalState) -> dict[str, Any]:
        draft = await self._repository.get(state["draft_id"])
        if draft is None:
            raise TicketDraftNotFoundError(state["draft_id"])
        if draft.status != "draft":
            raise TicketDraftStateConflictError(draft.id)
        return {
            "draft_version": draft.version,
            "draft_snapshot": draft.model_dump(mode="json"),
            "executed_nodes": ["load_draft"],
        }

    async def await_decision(self, state: ApprovalState) -> dict[str, Any]:
        raw_decision = interrupt(
            {
                "type": "ticket_approval",
                "thread_id": state["thread_id"],
                "draft_id": state["draft_id"],
                "draft_version": state["draft_version"],
                "draft": state["draft_snapshot"],
            },
            response_schema=ApprovalDecisionRequest,
        )
        decision = ApprovalDecisionRequest.model_validate(raw_decision)
        return {
            "decision": decision.decision,
            "decision_note": decision.note,
            "executed_nodes": ["await_decision"],
        }

    async def apply_decision(self, state: ApprovalState) -> dict[str, Any]:
        transition = await self._repository.finalize_approval(
            thread_id=state["thread_id"],
            draft_id=state["draft_id"],
            decision=state["decision"],
            note=state.get("decision_note"),
        )
        result = {
            "approval": {
                "thread_id": transition.approval.thread_id,
                "draft_id": transition.approval.draft_id,
                "draft_version": transition.approval.draft_version,
                "status": transition.approval.status,
                "note": transition.approval.note,
                "requested_at": transition.approval.requested_at.isoformat(),
                "decided_at": (
                    transition.approval.decided_at.isoformat()
                    if transition.approval.decided_at is not None
                    else None
                ),
            },
            "draft": transition.draft.model_dump(mode="json"),
        }
        return {
            "decision_result": result,
            "executed_nodes": ["apply_decision"],
        }


def build_approval_graph(
    repository: TicketDraftRepository,
    *,
    checkpointer: Any,
):
    """Compile the small approval-only graph with a persistent saver."""
    nodes = ApprovalGraphNodes(repository)
    graph = StateGraph(ApprovalState)
    graph.add_node("load_draft", nodes.load_draft)
    graph.add_node("await_decision", nodes.await_decision)
    graph.add_node("apply_decision", nodes.apply_decision)
    graph.add_edge(START, "load_draft")
    graph.add_edge("load_draft", "await_decision")
    graph.add_edge("await_decision", "apply_decision")
    graph.add_edge("apply_decision", END)
    return graph.compile(checkpointer=checkpointer)
