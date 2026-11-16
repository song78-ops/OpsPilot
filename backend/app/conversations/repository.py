"""SQLAlchemy persistence for Agent conversations and message history."""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.conversations.exceptions import (
    AgentIdempotencyConflictError,
    ConversationNotFoundError,
    ConversationPersistenceError,
)
from app.conversations.types import (
    AgentRequestRecord,
    ConversationMessageRecord,
    ConversationRecord,
    ConversationRole,
    ConversationSummary,
)


class ConversationBase(DeclarativeBase):
    pass


class ConversationRow(ConversationBase):
    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_ticket_draft_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )


class ConversationMessageRow(ConversationBase):
    __tablename__ = "agent_conversation_messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    business_reference_id: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class AgentRequestRow(ConversationBase):
    __tablename__ = "agent_request_runs"

    request_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    request_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("agent_conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ConversationRepository(Protocol):
    async def create(self) -> ConversationRecord:
        ...

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        ...

    async def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> list[ConversationMessageRecord]:
        ...

    async def count_messages(self, conversation_id: str) -> int:
        ...

    async def list_conversations(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationSummary], int]:
        ...

    async def list_ticket_reference_ids(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
    ) -> list[str]:
        ...

    async def append_turn(
        self,
        *,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        intent: str | None,
        status: str | None,
        tool_results: list[dict[str, str | bool | None]],
        last_ticket_draft_id: str | None,
    ) -> None:
        ...

    async def clear_last_ticket_draft_id(
        self,
        conversation_id: str,
    ) -> None:
        ...

    async def claim_request(
        self,
        *,
        request_key: str,
        fingerprint: str,
        request_id: str,
        request_summary: str,
    ) -> AgentRequestRecord:
        ...

    async def bind_request_conversation(
        self,
        *,
        request_key: str,
        conversation_id: str,
    ) -> None:
        ...

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
        tool_results: list[dict[str, str | bool | None]],
        last_ticket_draft_id: str | None,
    ) -> None:
        ...

    async def fail_request(
        self,
        *,
        request_key: str,
        error_code: str,
    ) -> None:
        ...

    async def close(self) -> None:
        ...


class SQLAlchemyConversationRepository:
    """SQLite conversation storage isolated from ticket and approval databases."""

    def __init__(self, database_url: str) -> None:
        parsed_url = make_url(database_url)
        if (
            parsed_url.get_backend_name() == "sqlite"
            and parsed_url.database
            and parsed_url.database != ":memory:"
        ):
            Path(parsed_url.database).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        self._engine: AsyncEngine = create_async_engine(database_url)
        self._session_factory = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
        )
        self._schema_ready = False
        self._lock = asyncio.Lock()

    async def create(self) -> ConversationRecord:
        await self._ensure_schema()
        now = datetime.now(timezone.utc)
        row = ConversationRow(
            id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            last_ticket_draft_id=None,
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(row)
                    await session.flush()
                    return self._conversation(row)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def get(self, conversation_id: str) -> ConversationRecord | None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                row = await session.get(ConversationRow, conversation_id)
                return self._conversation(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int,
    ) -> list[ConversationMessageRecord]:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                rows = (
                    await session.scalars(
                        select(ConversationMessageRow)
                        .where(
                            ConversationMessageRow.conversation_id
                            == conversation_id
                        )
                        .order_by(
                            ConversationMessageRow.id.desc()
                        )
                        .limit(limit)
                    )
                ).all()
                return [
                    self._message(row)
                    for row in reversed(rows)
                ]
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def count_messages(self, conversation_id: str) -> int:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                value = await session.scalar(
                    select(func.count())
                    .select_from(ConversationMessageRow)
                    .where(
                        ConversationMessageRow.conversation_id
                        == conversation_id
                    )
                )
                return int(value or 0)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def list_conversations(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[ConversationSummary], int]:
        await self._ensure_schema()
        first_user_message = (
            select(ConversationMessageRow.content)
            .where(
                ConversationMessageRow.conversation_id == ConversationRow.id,
                ConversationMessageRow.role == "user",
            )
            .order_by(ConversationMessageRow.id.asc())
            .limit(1)
            .correlate(ConversationRow)
            .scalar_subquery()
        )
        try:
            async with self._session_factory() as session:
                rows = (
                    await session.execute(
                        select(
                            ConversationRow,
                            first_user_message.label("first_user_message"),
                        )
                        .order_by(
                            ConversationRow.updated_at.desc(),
                            ConversationRow.id.desc(),
                        )
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
                total = await session.scalar(
                    select(func.count()).select_from(ConversationRow)
                )
                return (
                    [
                        ConversationSummary(
                            conversation=self._conversation(row),
                            title=self._title(first_message),
                        )
                        for row, first_message in rows
                    ],
                    int(total or 0),
                )
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def list_ticket_reference_ids(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
    ) -> list[str]:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                rows = (
                    await session.scalars(
                        select(ConversationMessageRow.business_reference_id)
                        .where(
                            ConversationMessageRow.conversation_id
                            == conversation_id,
                            ConversationMessageRow.business_reference_id
                            .is_not(None),
                        )
                        .order_by(ConversationMessageRow.id.desc())
                        .limit(limit)
                    )
                ).all()
                result: list[str] = []
                seen: set[str] = set()
                for value in rows:
                    if value is not None and value not in seen:
                        seen.add(value)
                        result.append(value)
                return result
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def append_turn(
        self,
        *,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        intent: str | None,
        status: str | None,
        tool_results: list[dict[str, str | bool | None]],
        last_ticket_draft_id: str | None,
    ) -> None:
        await self._ensure_schema()
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await self._append_turn_rows(
                        session,
                        conversation_id=conversation_id,
                        user_content=user_content,
                        assistant_content=assistant_content,
                        intent=intent,
                        status=status,
                        tool_results=tool_results,
                        last_ticket_draft_id=last_ticket_draft_id,
                        now=now,
                    )
        except ConversationNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def claim_request(
        self,
        *,
        request_key: str,
        fingerprint: str,
        request_id: str,
        request_summary: str,
    ) -> AgentRequestRecord:
        """Reserve one durable Agent request or return its completed result."""
        await self._ensure_schema()
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(AgentRequestRow, request_key)
                    if row is None:
                        row = AgentRequestRow(
                            request_key=request_key,
                            request_id=request_id,
                            request_summary=request_summary,
                            fingerprint=fingerprint,
                            conversation_id=None,
                            status="in_progress",
                            response_json=None,
                            error_code=None,
                            attempt_count=1,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(row)
                    else:
                        if row.fingerprint != fingerprint:
                            raise AgentIdempotencyConflictError()
                        if row.request_id not in {None, request_id}:
                            raise AgentIdempotencyConflictError()
                        if (
                            row.request_summary is not None
                            and row.request_summary != request_summary
                        ):
                            raise AgentIdempotencyConflictError()
                        if row.request_id is None:
                            row.request_id = request_id
                        if row.request_summary is None:
                            row.request_summary = request_summary
                        if row.status != "completed":
                            row.status = "in_progress"
                            row.error_code = None
                            row.attempt_count += 1
                            row.updated_at = now
                    await session.flush()
                    return self._request(row)
        except AgentIdempotencyConflictError:
            raise
        except IntegrityError:
            existing = await self._get_request(request_key)
            if existing is None:
                raise ConversationPersistenceError()
            if (
                existing.fingerprint != fingerprint
                or existing.request_id not in {None, request_id}
                or (
                    existing.request_summary is not None
                    and existing.request_summary != request_summary
                )
            ):
                raise AgentIdempotencyConflictError()
            return existing
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def bind_request_conversation(
        self,
        *,
        request_key: str,
        conversation_id: str,
    ) -> None:
        """Persist the generated conversation ID before workflow execution."""
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(AgentRequestRow, request_key)
                    if row is None:
                        raise ConversationPersistenceError()
                    if row.conversation_id not in {None, conversation_id}:
                        raise AgentIdempotencyConflictError()
                    row.conversation_id = conversation_id
                    row.updated_at = datetime.now(timezone.utc)
        except (AgentIdempotencyConflictError, ConversationPersistenceError):
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

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
        tool_results: list[dict[str, str | bool | None]],
        last_ticket_draft_id: str | None,
    ) -> None:
        """Commit the conversation turn and replay response atomically."""
        await self._ensure_schema()
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    request_row = await session.get(
                        AgentRequestRow,
                        request_key,
                    )
                    if request_row is None:
                        raise ConversationPersistenceError()
                    if request_row.status == "completed":
                        return
                    if request_row.conversation_id not in {
                        None,
                        conversation_id,
                    }:
                        raise AgentIdempotencyConflictError()
                    await self._append_turn_rows(
                        session,
                        conversation_id=conversation_id,
                        user_content=user_content,
                        assistant_content=assistant_content,
                        intent=intent,
                        status=status,
                        tool_results=tool_results,
                        last_ticket_draft_id=last_ticket_draft_id,
                        now=now,
                    )
                    request_row.conversation_id = conversation_id
                    request_row.status = "completed"
                    request_row.response_json = response_json
                    request_row.error_code = None
                    request_row.updated_at = now
        except (
            AgentIdempotencyConflictError,
            ConversationNotFoundError,
            ConversationPersistenceError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def fail_request(
        self,
        *,
        request_key: str,
        error_code: str,
    ) -> None:
        """Record a retryable failure without caching an HTTP error response."""
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(AgentRequestRow, request_key)
                    if row is None or row.status == "completed":
                        return
                    row.status = "failed"
                    row.error_code = error_code
                    row.updated_at = datetime.now(timezone.utc)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def _append_turn_rows(
        self,
        session: AsyncSession,
        *,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        intent: str | None,
        status: str | None,
        tool_results: list[dict[str, str | bool | None]],
        last_ticket_draft_id: str | None,
        now: datetime,
    ) -> None:
        conversation = await session.get(
            ConversationRow,
            conversation_id,
        )
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        session.add(
            ConversationMessageRow(
                conversation_id=conversation_id,
                role="user",
                content=user_content,
                intent=intent,
                status=None,
                tool_name=None,
                tool_status=None,
                business_reference_id=None,
                created_at=now,
            )
        )
        for result in tool_results:
            session.add(
                ConversationMessageRow(
                    conversation_id=conversation_id,
                    role="tool",
                    content=str(result.get("message") or ""),
                    intent=intent,
                    status=None,
                    tool_name=str(result.get("name") or ""),
                    tool_status=str(result.get("status") or ""),
                    business_reference_id=(
                        str(result["draft_id"])
                        if result.get("draft_id")
                        else None
                    ),
                    created_at=now,
                )
            )
        session.add(
            ConversationMessageRow(
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                intent=intent,
                status=status,
                tool_name=None,
                tool_status=None,
                business_reference_id=last_ticket_draft_id,
                created_at=now,
            )
        )
        conversation.updated_at = now
        if last_ticket_draft_id is not None:
            conversation.last_ticket_draft_id = last_ticket_draft_id

    async def clear_last_ticket_draft_id(
        self,
        conversation_id: str,
    ) -> None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    row = await session.get(ConversationRow, conversation_id)
                    if row is not None:
                        row.last_ticket_draft_id = None
                        row.updated_at = datetime.now(timezone.utc)
        except SQLAlchemyError as exc:
            raise ConversationPersistenceError() from exc

    async def close(self) -> None:
        await self._engine.dispose()

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._lock:
            if self._schema_ready:
                return
            try:
                async with self._engine.begin() as connection:
                    await connection.run_sync(
                        ConversationBase.metadata.create_all
                    )
                    columns = await connection.exec_driver_sql(
                        "PRAGMA table_info(agent_request_runs)"
                    )
                    column_names = {
                        str(row[1]) for row in columns.fetchall()
                    }
                    if "request_id" not in column_names:
                        await connection.exec_driver_sql(
                            "ALTER TABLE agent_request_runs "
                            "ADD COLUMN request_id VARCHAR(128)"
                        )
                    if "request_summary" not in column_names:
                        await connection.exec_driver_sql(
                            "ALTER TABLE agent_request_runs "
                            "ADD COLUMN request_summary TEXT"
                        )
                self._schema_ready = True
            except SQLAlchemyError as exc:
                raise ConversationPersistenceError() from exc

    @staticmethod
    def _conversation(row: ConversationRow) -> ConversationRecord:
        return ConversationRecord(
            id=row.id,
            created_at=SQLAlchemyConversationRepository._utc(row.created_at),
            updated_at=SQLAlchemyConversationRepository._utc(row.updated_at),
            last_ticket_draft_id=row.last_ticket_draft_id,
        )

    @staticmethod
    def _message(row: ConversationMessageRow) -> ConversationMessageRecord:
        return ConversationMessageRecord(
            id=row.id,
            conversation_id=row.conversation_id,
            role=row.role,  # type: ignore[arg-type]
            content=row.content,
            intent=row.intent,
            status=row.status,
            tool_name=row.tool_name,
            tool_status=row.tool_status,
            business_reference_id=row.business_reference_id,
            created_at=SQLAlchemyConversationRepository._utc(row.created_at),
        )

    async def _get_request(
        self,
        request_key: str,
    ) -> AgentRequestRecord | None:
        async with self._session_factory() as session:
            row = await session.get(AgentRequestRow, request_key)
            return self._request(row) if row is not None else None

    @staticmethod
    def _request(row: AgentRequestRow) -> AgentRequestRecord:
        return AgentRequestRecord(
            request_key=row.request_key,
            request_id=row.request_id,
            request_summary=row.request_summary,
            fingerprint=row.fingerprint,
            conversation_id=row.conversation_id,
            status=row.status,  # type: ignore[arg-type]
            response_json=row.response_json,
            error_code=row.error_code,
            attempt_count=row.attempt_count,
            created_at=SQLAlchemyConversationRepository._utc(row.created_at),
            updated_at=SQLAlchemyConversationRepository._utc(row.updated_at),
        )

    @staticmethod
    def _title(first_message: str | None) -> str:
        if first_message is None:
            return "新会话"
        normalized = " ".join(first_message.split())
        if not normalized:
            return "新会话"
        return normalized if len(normalized) <= 36 else f"{normalized[:36]}…"

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(
            tzinfo=timezone.utc
        )
