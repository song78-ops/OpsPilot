"""Conversation memory orchestration and bounded model context."""

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.conversations.exceptions import ConversationNotFoundError
from app.conversations.repository import ConversationRepository
from app.conversations.types import (
    AgentRequestRecord,
    ConversationContext,
    ConversationHistory,
    ConversationMessageRecord,
    ConversationRecord,
    ConversationSummary,
    ToolResultRecord,
)
from app.schemas.ticket import TicketDraftResponse
from app.tickets.exceptions import TicketDraftNotFoundError
from app.tickets.service import TicketDraftService

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(text: str) -> int:
    """Conservatively estimate model tokens without loading a tokenizer model."""
    return max(
        1,
        len(_CJK_RE.findall(text)) + len(_WORD_RE.findall(text)),
    )


def trim_history(
    messages: list[ConversationMessageRecord],
    *,
    max_messages: int,
    token_budget: int,
) -> list[ConversationMessageRecord]:
    """Keep the newest complete history messages within both limits."""
    selected: list[ConversationMessageRecord] = []
    used_tokens = 0
    for message in reversed(messages):
        if len(selected) >= max_messages:
            break
        message_tokens = estimate_tokens(message.content) + 4
        if used_tokens + message_tokens > token_budget:
            continue
        selected.append(message)
        used_tokens += message_tokens
    selected.reverse()
    return selected


def format_history(messages: list[ConversationMessageRecord]) -> str:
    if not messages:
        return ""
    lines = ["<untrusted_conversation_history>"]
    for message in messages:
        if message.role == "tool":
            label = f"TOOL[{message.tool_name or 'unknown'}]"
            detail = f"status={message.tool_status or 'unknown'}"
            lines.append(f"{label} ({detail}): {message.content}")
        else:
            lines.append(f"{message.role.upper()}: {message.content}")
    lines.append("</untrusted_conversation_history>")
    return "\n".join(lines)


class ConversationMemoryService:
    """Resolve conversation IDs and build verified bounded context."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        ticket_service: TicketDraftService,
        max_history_messages: int,
        history_token_budget: int,
    ) -> None:
        self._repository = repository
        self._ticket_service = ticket_service
        self._max_history_messages = max_history_messages
        self._history_token_budget = history_token_budget
        self._locks: dict[str, asyncio.Lock] = {}

    async def begin_or_resume(
        self,
        conversation_id: str | None,
    ) -> ConversationRecord:
        if conversation_id is None:
            return await self._repository.create()
        conversation = await self._repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    @asynccontextmanager
    async def conversation_lock(
        self,
        conversation_id: str,
    ) -> AsyncIterator[None]:
        lock = self._locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            yield

    async def build_context(
        self,
        conversation: ConversationRecord,
        *,
        max_messages: int | None = None,
        token_budget: int | None = None,
    ) -> ConversationContext:
        message_limit = max(
            50,
            (max_messages or self._max_history_messages) * 4,
        )
        raw_messages = await self._repository.list_messages(
            conversation.id,
            limit=message_limit,
        )
        history = trim_history(
            raw_messages,
            max_messages=max_messages or self._max_history_messages,
            token_budget=token_budget or self._history_token_budget,
        )
        reference_ids = await self._repository.list_ticket_reference_ids(
            conversation.id
        )
        drafts: list[TicketDraftResponse] = []
        valid_ids: set[str] = set()
        for draft_id in reference_ids:
            try:
                draft = await self._ticket_service.get(draft_id)
            except TicketDraftNotFoundError:
                logger.warning(
                    "Ignoring stale conversation ticket reference "
                    "conversation_id=%s draft_id=%s",
                    conversation.id,
                    draft_id,
                )
                continue
            drafts.append(draft)
            valid_ids.add(draft.id)

        last_ticket_draft_id = conversation.last_ticket_draft_id
        if (
            last_ticket_draft_id is not None
            and last_ticket_draft_id not in valid_ids
        ):
            await self._repository.clear_last_ticket_draft_id(
                conversation.id
            )
            last_ticket_draft_id = None

        last_ticket = next(
            (
                draft
                for draft in drafts
                if draft.id == last_ticket_draft_id
            ),
            None,
        )
        editable_ids = {
            draft.id for draft in drafts if draft.status == "draft"
        }
        return ConversationContext(
            conversation=ConversationRecord(
                id=conversation.id,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                last_ticket_draft_id=last_ticket_draft_id,
            ),
            messages=history,
            candidate_drafts=drafts,
            last_ticket_draft=last_ticket,
            target_ambiguous=len(editable_ids) > 1,
            metadata={
                "history_messages": len(history),
                "history_tokens": sum(
                    estimate_tokens(message.content) + 4
                    for message in history
                ),
                "candidate_drafts": len(drafts),
            },
        )

    async def record_turn(
        self,
        *,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        intent: str | None,
        status: str | None,
        tool_results: list[ToolResultRecord],
        last_ticket_draft_id: str | None,
    ) -> None:
        await self._repository.append_turn(
            conversation_id=conversation_id,
            user_content=user_content,
            assistant_content=assistant_content,
            intent=intent,
            status=status,
            tool_results=[
                {
                    "name": result.name,
                    "status": result.status,
                    "message": result.message,
                    "draft_id": result.draft_id,
                }
                for result in tool_results
            ],
            last_ticket_draft_id=last_ticket_draft_id,
        )

    async def record_failure(
        self,
        *,
        conversation_id: str,
        user_content: str,
        error_code: str,
    ) -> None:
        await self._repository.append_turn(
            conversation_id=conversation_id,
            user_content=user_content,
            assistant_content=f"Agent 请求失败：{error_code}",
            intent=None,
            status="service_error",
            tool_results=[],
            last_ticket_draft_id=None,
        )

    async def claim_request(
        self,
        *,
        message: str,
        request_key: str,
    ) -> AgentRequestRecord:
        """Claim a request key and reject reuse for different payloads."""
        fingerprint = hashlib.sha256(
            json.dumps(
                {"message": message},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return await self._repository.claim_request(
            request_key=request_key,
            fingerprint=fingerprint,
        )

    async def bind_request_conversation(
        self,
        *,
        request_key: str,
        conversation_id: str,
    ) -> None:
        await self._repository.bind_request_conversation(
            request_key=request_key,
            conversation_id=conversation_id,
        )

    async def complete_request_turn(
        self,
        *,
        request_key: str,
        response_json: str,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        intent: str | None,
        status: str | None,
        tool_results: list[ToolResultRecord],
        last_ticket_draft_id: str | None,
    ) -> None:
        await self._repository.complete_request_turn(
            request_key=request_key,
            response_json=response_json,
            conversation_id=conversation_id,
            user_content=user_content,
            assistant_content=assistant_content,
            intent=intent,
            status=status,
            tool_results=[
                {
                    "name": result.name,
                    "status": result.status,
                    "message": result.message,
                    "draft_id": result.draft_id,
                }
                for result in tool_results
            ],
            last_ticket_draft_id=last_ticket_draft_id,
        )

    async def fail_request(
        self,
        *,
        request_key: str,
        error_code: str,
    ) -> None:
        await self._repository.fail_request(
            request_key=request_key,
            error_code=error_code,
        )

    async def get_history(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> ConversationHistory:
        conversation = await self._repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        messages = await self._repository.list_messages(
            conversation_id,
            limit=limit,
        )
        total = await self._repository.count_messages(conversation_id)
        return ConversationHistory(
            conversation=conversation,
            messages=messages,
            total=total,
        )

    async def get_ticket_references(
        self,
        conversation_id: str,
    ) -> list[str]:
        conversation = await self._repository.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        references = await self._repository.list_ticket_reference_ids(
            conversation_id
        )
        verified: list[str] = []
        for draft_id in references:
            try:
                await self._ticket_service.get(draft_id)
            except TicketDraftNotFoundError:
                continue
            verified.append(draft_id)
        return verified

    async def list_conversations(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationSummary], int]:
        return await self._repository.list_conversations(
            limit=limit,
            offset=offset,
        )


def ticket_context_text(context: ConversationContext) -> str:
    """Create trusted ticket-reference instructions for the tool model."""
    if not context.candidate_drafts:
        return (
            "<trusted_ticket_context>\n"
            "This conversation has no previously verified ticket drafts.\n"
            "</trusted_ticket_context>"
        )

    lines = ["<trusted_ticket_context>"]
    if context.last_ticket_draft is not None:
        lines.append(
            "last_ticket_draft_id="
            f"{context.last_ticket_draft.id} "
            f"status={context.last_ticket_draft.status}"
        )
    for draft in context.candidate_drafts:
        lines.append(
            f"- draft_id={draft.id} status={draft.status}"
        )
    lines.append(
        "Only these draft IDs belong to this conversation. Never use a "
        "draft ID from another conversation."
    )
    if context.target_ambiguous:
        lines.append(
            "Multiple editable drafts are possible targets. If the current "
            "request does not explicitly contain the target draft_id, ask "
            "the user to specify it and do not call update_ticket_draft."
        )
    elif context.last_ticket_draft is not None:
        lines.append(
            "For a follow-up reference such as '刚才那个工单', use "
            "last_ticket_draft_id when that draft is editable."
        )
    lines.append("</trusted_ticket_context>")
    return "\n".join(lines)
