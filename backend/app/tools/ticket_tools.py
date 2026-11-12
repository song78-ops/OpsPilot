"""Validated function-calling tools for ticket drafts."""

import json
import hashlib
from typing import Literal

from pydantic import BaseModel, ValidationError

from app.core.exceptions import ApplicationError
from app.llm.base import LLMToolCall
from app.schemas.ticket import (
    CreateTicketDraftArgs,
    GetTicketDraftArgs,
    TicketDraftResponse,
    TicketDraftUpdateRequest,
    UpdateTicketDraftArgs,
)
from app.tickets.exceptions import TicketDraftValidationError
from app.tickets.service import TicketDraftService

CREATE_TICKET_DRAFT = "create_ticket_draft"
GET_TICKET_DRAFT = "get_ticket_draft"
UPDATE_TICKET_DRAFT = "update_ticket_draft"
ALLOWED_TOOL_NAMES = frozenset(
    {
        CREATE_TICKET_DRAFT,
        GET_TICKET_DRAFT,
        UPDATE_TICKET_DRAFT,
    }
)


def _tool(
    name: str,
    description: str,
    parameters: dict,
) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TICKET_TOOL_DEFINITIONS = [
    _tool(
        CREATE_TICKET_DRAFT,
        (
            "Save a ticket draft after all required fields are known. "
            "This never creates a formal or approved ticket."
        ),
        CreateTicketDraftArgs.model_json_schema(),
    ),
    _tool(
        GET_TICKET_DRAFT,
        "Get a saved ticket draft by its returned draft ID.",
        GetTicketDraftArgs.model_json_schema(),
    ),
    _tool(
        UPDATE_TICKET_DRAFT,
        (
            "Update allowed fields on a saved ticket draft. "
            "Formal ticket submission is not available."
        ),
        UpdateTicketDraftArgs.model_json_schema(),
    ),
]


class ToolExecutionOutcome(BaseModel):
    ok: bool
    status: Literal[
        "created",
        "retrieved",
        "updated",
        "needs_more_info",
        "error",
    ]
    message: str
    draft: TicketDraftResponse | None = None
    created: bool = False
    error_code: str | None = None
    missing_fields: list[str] = []


class TicketToolExecutor:
    """Strict allowlist executor for native model tool calls."""

    def __init__(self, service: TicketDraftService) -> None:
        self._service = service

    async def execute(
        self,
        call: LLMToolCall,
        *,
        conversation_id: str | None,
    ) -> ToolExecutionOutcome:
        if call.name not in ALLOWED_TOOL_NAMES:
            return ToolExecutionOutcome(
                ok=False,
                status="error",
                message=f"Tool '{call.name}' is not allowed.",
                error_code="UNKNOWN_TOOL",
            )

        try:
            arguments = json.loads(call.arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
            return await self._dispatch(
                call=call,
                arguments=arguments,
                conversation_id=conversation_id,
            )
        except ValidationError as exc:
            return ToolExecutionOutcome(
                ok=False,
                status="error",
                message="Tool arguments failed validation.",
                error_code="INVALID_TOOL_ARGUMENTS",
            )
        except (json.JSONDecodeError, ValueError):
            return ToolExecutionOutcome(
                ok=False,
                status="error",
                message="Tool arguments were not valid JSON.",
                error_code="INVALID_TOOL_ARGUMENTS",
            )
        except TicketDraftValidationError as exc:
            labels = {
                "title": "标题",
                "description": "问题描述",
                "device_or_system": "设备或系统名称",
            }
            missing = "、".join(
                labels.get(field, field) for field in exc.missing_fields
            )
            return ToolExecutionOutcome(
                ok=False,
                status="needs_more_info",
                message=(
                    f"缺少必要字段：{missing}。请补充后再保存草稿。"
                    if missing
                    else exc.message
                ),
                error_code="TICKET_DRAFT_MISSING_FIELDS",
                missing_fields=exc.missing_fields,
            )
        except ApplicationError as exc:
            return ToolExecutionOutcome(
                ok=False,
                status="error",
                message=exc.message,
                error_code=exc.code,
            )
        except Exception:
            return ToolExecutionOutcome(
                ok=False,
                status="error",
                message="Tool execution failed unexpectedly.",
                error_code="TOOL_EXECUTION_ERROR",
            )

    async def _dispatch(
        self,
        *,
        call: LLMToolCall,
        arguments: dict,
        conversation_id: str | None,
    ) -> ToolExecutionOutcome:
        if call.name == CREATE_TICKET_DRAFT:
            idempotency_key = hashlib.sha256(
                f"{call.name}:{call.id}".encode("utf-8")
            ).hexdigest()
            result = await self._service.create(
                args=CreateTicketDraftArgs.model_validate(arguments),
                idempotency_key=idempotency_key,
            )
            draft = result.draft
            return ToolExecutionOutcome(
                ok=True,
                status="created",
                message=(
                    f"工单草稿已保存，ID: {draft.id}。"
                    if result.created
                    else f"该工具调用已存在，返回工单草稿 ID: {draft.id}。"
                ),
                draft=draft,
                created=result.created,
            )

        if call.name == GET_TICKET_DRAFT:
            args = GetTicketDraftArgs.model_validate(arguments)
            draft = await self._service.get(args.draft_id)
            return ToolExecutionOutcome(
                ok=True,
                status="retrieved",
                message=f"已查询到工单草稿 ID: {draft.id}。",
                draft=draft,
            )

        args = UpdateTicketDraftArgs.model_validate(arguments)
        draft = await self._service.update(
            args.draft_id,
            TicketDraftUpdateRequest(
                title=args.title,
                description=args.description,
                device_or_system=args.device_or_system,
            ),
        )
        return ToolExecutionOutcome(
            ok=True,
            status="updated",
            message=f"工单草稿 {draft.id} 已更新，尚未创建正式工单。",
            draft=draft,
        )

    @staticmethod
    def tool_message(
        call: LLMToolCall,
        outcome: ToolExecutionOutcome,
    ) -> dict:
        return {
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(
                outcome.model_dump(mode="json"),
                ensure_ascii=False,
            ),
        }

