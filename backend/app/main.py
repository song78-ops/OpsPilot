"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.deps import (
    close_application_resources,
    get_ticket_repository,
)
from app.api.router import api_router
from app.approvals.runtime import create_approval_runtime
from app.core.config import get_settings
from app.core.exceptions import ApplicationError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own persistent approval checkpoints for the application lifetime."""
    runtime = None
    try:
        settings = get_settings()
        repository = get_ticket_repository(settings)
        runtime = await create_approval_runtime(
            checkpoint_path=settings.resolved_approval_checkpoint_path,
            repository=repository,
            max_execution_steps=settings.agent_max_execution_steps,
        )
        application.state.approval_service = runtime.service
        yield
    finally:
        if runtime is not None:
            await runtime.close()
        await close_application_resources()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="OpsPilot 企业知识库与智能工单 Agent 平台 API",
        lifespan=lifespan,
    )
    application.include_router(api_router)

    @application.exception_handler(ApplicationError)
    async def handle_application_error(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        logger.warning(
            "Application error on %s %s: code=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        )

    @application.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "Unexpected error on %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected server error occurred.",
                }
            },
        )

    return application


app = create_app()

