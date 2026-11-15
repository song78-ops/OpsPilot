"""LangGraph agent run endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.agents.service import AgentService
from app.api.deps import (
    get_agent_service,
    get_conversation_memory_service,
    require_local_agent_access,
)
from app.conversations.service import ConversationMemoryService
from app.schemas.agent import AgentRunRequest, AgentRunResponse
from app.schemas.conversation import (
    ConversationHistoryResponse,
    ConversationMessageResponse,
)

router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    dependencies=[Depends(require_local_agent_access)],
)


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentRunResponse:
    """Run one supervised LangGraph workflow."""
    return await service.run(
        message=payload.message,
        conversation_id=payload.conversation_id,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationHistoryResponse,
)
async def get_conversation_history(
    conversation_id: str,
    service: Annotated[
        ConversationMemoryService,
        Depends(get_conversation_memory_service),
    ],
    limit: int = Query(default=50, ge=1, le=200),
) -> ConversationHistoryResponse:
    """Read persisted conversation messages without exposing other sessions."""
    history = await service.get_history(conversation_id, limit=limit)
    references = await service.get_ticket_references(conversation_id)
    return ConversationHistoryResponse(
        conversation_id=history.conversation.id,
        created_at=history.conversation.created_at,
        updated_at=history.conversation.updated_at,
        last_ticket_draft_id=history.conversation.last_ticket_draft_id,
        ticket_references=references,
        total=history.total,
        messages=[
            ConversationMessageResponse(
                id=message.id,
                role=message.role,
                content=message.content,
                intent=message.intent,
                status=message.status,
                tool_name=message.tool_name,
                tool_status=message.tool_status,
                business_reference_id=message.business_reference_id,
                created_at=message.created_at,
            )
            for message in history.messages
        ],
    )

