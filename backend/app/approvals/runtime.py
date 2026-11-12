"""Lifespan-owned SQLite checkpointer runtime."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.approvals.service import TicketApprovalService
from app.approvals.workflow import ApprovalWorkflow
from app.tickets.repository import TicketDraftRepository


@dataclass(slots=True)
class ApprovalRuntime:
    connection: aiosqlite.Connection
    checkpointer: AsyncSqliteSaver
    service: TicketApprovalService

    async def close(self) -> None:
        await self.connection.close()


async def create_approval_runtime(
    *,
    checkpoint_path: Path,
    repository: TicketDraftRepository,
    max_execution_steps: int = 6,
) -> ApprovalRuntime:
    """Open the approval checkpoint DB once and own it for app lifetime."""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(str(checkpoint_path))
    try:
        await connection.execute("PRAGMA busy_timeout = 5000")
        await connection.execute("PRAGMA journal_mode = WAL")
        serializer = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_json_modules=None,
            allowed_msgpack_modules=None,
        )
        checkpointer = AsyncSqliteSaver(connection, serde=serializer)
        await checkpointer.setup()
        workflow = ApprovalWorkflow(
            repository=repository,
            checkpointer=checkpointer,
            max_execution_steps=max_execution_steps,
        )
        service = TicketApprovalService(
            repository=repository,
            workflow=workflow,
        )
        return ApprovalRuntime(
            connection=connection,
            checkpointer=checkpointer,
            service=service,
        )
    except BaseException:
        await connection.close()
        raise
