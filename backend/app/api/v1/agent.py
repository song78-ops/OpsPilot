"""LangGraph agent run endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.service import AgentService
from app.api.deps import get_agent_service
from app.schemas.agent import AgentRunRequest, AgentRunResponse

router = APIRouter(prefix="/agent", tags=["agent"])


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

