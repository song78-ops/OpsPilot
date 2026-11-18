"""Health check endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Any, Annotated

from app.api.deps import get_llm_budget_controller
from app.core.config import Settings, get_settings
from app.llm.budget import LLMBudgetController

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Report whether the API process is running."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
    )


@router.get("/health/llm-budget")
async def llm_budget(
    settings: Annotated[Settings, Depends(get_settings)],
    controller: Annotated[
        LLMBudgetController,
        Depends(get_llm_budget_controller),
    ],
) -> dict[str, Any]:
    """Report paid-model budget usage without exposing credentials."""
    return {
        "provider": settings.llm_provider,
        "budget": await controller.snapshot(),
    }

