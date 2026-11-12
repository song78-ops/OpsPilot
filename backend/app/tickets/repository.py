"""Repository interface and SQLAlchemy SQLite implementation."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.schemas.ticket import (
    TicketDraftResponse,
    TicketDraftUpdateRequest,
)
from app.approvals.types import (
    TicketApprovalRecord,
    TicketApprovalTransition,
)
from app.tickets.exceptions import (
    TicketApprovalStateConflictError,
    TicketDraftStateConflictError,
    TicketDraftVersionConflictError,
    TicketPersistenceError,
)


class TicketBase(DeclarativeBase):
    pass


class TicketDraftRow(TicketBase):
    __tablename__ = "ticket_drafts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    device_or_system: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
    )
    version: Mapped[int] = mapped_column(
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


class TicketApprovalRow(TicketBase):
    __tablename__ = "ticket_approvals"

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
    )
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class TicketApprovalAuditRow(TicketBase):
    __tablename__ = "ticket_approval_audit"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "action",
            name="uq_ticket_approval_audit_action",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


@dataclass(frozen=True, slots=True)
class TicketDraftWrite:
    draft: TicketDraftResponse
    created: bool


class TicketDraftRepository(Protocol):
    async def create(
        self,
        *,
        idempotency_key: str,
        title: str,
        description: str,
        device_or_system: str,
    ) -> TicketDraftWrite:
        ...

    async def get(self, draft_id: str) -> TicketDraftResponse | None:
        ...

    async def update(
        self,
        draft_id: str,
        values: TicketDraftUpdateRequest,
    ) -> TicketDraftResponse | None:
        ...

    async def list(self) -> list[TicketDraftResponse]:
        ...

    async def get_approval(
        self,
        thread_id: str,
    ) -> TicketApprovalRecord | None:
        ...

    async def get_approval_by_draft(
        self,
        draft_id: str,
    ) -> TicketApprovalRecord | None:
        ...

    async def request_approval(
        self,
        *,
        draft_id: str,
        thread_id: str,
        expected_version: int,
    ) -> TicketApprovalTransition:
        ...

    async def finalize_approval(
        self,
        *,
        thread_id: str,
        draft_id: str,
        decision: str,
        note: str | None,
    ) -> TicketApprovalTransition:
        ...

    async def close(self) -> None:
        ...


class SQLAlchemyTicketDraftRepository:
    """SQLite persistence with unique tool-call idempotency."""

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

    async def create(
        self,
        *,
        idempotency_key: str,
        title: str,
        description: str,
        device_or_system: str,
    ) -> TicketDraftWrite:
        await self._ensure_schema()
        try:
            existing = await self._get_by_idempotency_key(idempotency_key)
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc
        if existing is not None:
            return TicketDraftWrite(draft=existing, created=False)

        now = datetime.now(timezone.utc)
        row = TicketDraftRow(
            id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
            title=title,
            description=description,
            device_or_system=device_or_system,
            status="draft",
            version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(row)
            return TicketDraftWrite(draft=self._to_response(row), created=True)
        except IntegrityError:
            existing = await self._get_by_idempotency_key(idempotency_key)
            if existing is not None:
                return TicketDraftWrite(draft=existing, created=False)
            raise TicketPersistenceError()
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def get(self, draft_id: str) -> TicketDraftResponse | None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                row = await session.get(TicketDraftRow, draft_id)
                return self._to_response(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def update(
        self,
        draft_id: str,
        values: TicketDraftUpdateRequest,
    ) -> TicketDraftResponse | None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    field_values: dict[str, object] = {
                        "updated_at": datetime.now(timezone.utc),
                    }
                    if values.title is not None:
                        field_values["title"] = values.title
                    if values.description is not None:
                        field_values["description"] = values.description
                    if values.device_or_system is not None:
                        field_values["device_or_system"] = (
                            values.device_or_system
                        )
                    result = await session.execute(
                        update(TicketDraftRow)
                        .where(
                            TicketDraftRow.id == draft_id,
                            TicketDraftRow.status == "draft",
                        )
                        .values(
                            **field_values,
                            version=TicketDraftRow.version + 1,
                        )
                    )
                    if result.rowcount == 0:
                        existing = await session.get(TicketDraftRow, draft_id)
                        if existing is None:
                            return None
                        raise TicketDraftStateConflictError(draft_id)
                    row = await session.get(
                        TicketDraftRow,
                        draft_id,
                        populate_existing=True,
                    )
                    if row is None:
                        return None
                    return self._to_response(row)
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def get_approval(
        self,
        thread_id: str,
    ) -> TicketApprovalRecord | None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                row = await session.get(TicketApprovalRow, thread_id)
                return self._approval_to_record(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def get_approval_by_draft(
        self,
        draft_id: str,
    ) -> TicketApprovalRecord | None:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                row = await session.scalar(
                    select(TicketApprovalRow).where(
                        TicketApprovalRow.draft_id == draft_id
                    )
                )
                return self._approval_to_record(row) if row is not None else None
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def request_approval(
        self,
        *,
        draft_id: str,
        thread_id: str,
        expected_version: int,
    ) -> TicketApprovalTransition:
        await self._ensure_schema()
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    draft = await session.get(TicketDraftRow, draft_id)
                    if draft is None:
                        from app.tickets.exceptions import TicketDraftNotFoundError

                        raise TicketDraftNotFoundError(draft_id)
                    if draft.status != "draft":
                        raise TicketDraftStateConflictError(draft_id)
                    if draft.version != expected_version:
                        raise TicketDraftVersionConflictError(draft_id)
                    existing = await session.scalar(
                        select(TicketApprovalRow).where(
                            TicketApprovalRow.draft_id == draft_id
                        )
                    )
                    if existing is not None:
                        raise TicketApprovalStateConflictError(
                            f"Ticket draft '{draft_id}' already has an approval."
                        )
                    result = await session.execute(
                        update(TicketDraftRow)
                        .where(
                            TicketDraftRow.id == draft_id,
                            TicketDraftRow.status == "draft",
                            TicketDraftRow.version == expected_version,
                        )
                        .values(
                            status="pending_approval",
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        raise TicketDraftStateConflictError(draft_id)
                    approval_row = TicketApprovalRow(
                        thread_id=thread_id,
                        draft_id=draft_id,
                        draft_version=expected_version,
                        status="pending_approval",
                        note=None,
                        requested_at=now,
                        decided_at=None,
                    )
                    session.add(approval_row)
                    session.add(
                        TicketApprovalAuditRow(
                            thread_id=thread_id,
                            draft_id=draft_id,
                            action="request",
                            from_status="draft",
                            to_status="pending_approval",
                            draft_version=expected_version,
                            note=None,
                            created_at=now,
                        )
                    )
                    await session.flush()
                    draft.status = "pending_approval"
                    draft.updated_at = now
                    return TicketApprovalTransition(
                        approval=self._approval_to_record(approval_row),
                        draft=self._to_response(draft),
                    )
        except IntegrityError as exc:
            raise TicketApprovalStateConflictError(
                "The ticket draft already has an approval."
            ) from exc
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def finalize_approval(
        self,
        *,
        thread_id: str,
        draft_id: str,
        decision: str,
        note: str | None,
    ) -> TicketApprovalTransition:
        await self._ensure_schema()
        if decision not in {"approve", "reject"}:
            raise TicketApprovalStateConflictError(
                "Approval decision must be approve or reject."
            )
        target_status = "approved" if decision == "approve" else "rejected"
        action = "approve" if decision == "approve" else "reject"
        now = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    approval = await session.get(TicketApprovalRow, thread_id)
                    if approval is None or approval.draft_id != draft_id:
                        raise TicketApprovalStateConflictError(
                            "Approval mapping does not match this workflow."
                        )
                    if approval.status != "pending_approval":
                        raise TicketApprovalStateConflictError(
                            "Approval is no longer waiting for a decision."
                        )
                    draft = await session.get(TicketDraftRow, draft_id)
                    if draft is None or draft.status != "pending_approval":
                        raise TicketApprovalStateConflictError(
                            "Ticket draft is not pending approval."
                        )
                    if draft.version != approval.draft_version:
                        raise TicketDraftVersionConflictError(draft_id)
                    result = await session.execute(
                        update(TicketDraftRow)
                        .where(
                            TicketDraftRow.id == draft_id,
                            TicketDraftRow.status == "pending_approval",
                            TicketDraftRow.version == approval.draft_version,
                        )
                        .values(
                            status=target_status,
                            updated_at=now,
                        )
                    )
                    if result.rowcount != 1:
                        raise TicketApprovalStateConflictError(
                            "Ticket draft changed during the approval decision."
                        )
                    approval.status = target_status
                    approval.note = note
                    approval.decided_at = now
                    session.add(
                        TicketApprovalAuditRow(
                            thread_id=thread_id,
                            draft_id=draft_id,
                            action=action,
                            from_status="pending_approval",
                            to_status=target_status,
                            draft_version=approval.draft_version,
                            note=note,
                            created_at=now,
                        )
                    )
                    await session.flush()
                    draft.status = target_status
                    draft.updated_at = now
                    return TicketApprovalTransition(
                        approval=self._approval_to_record(approval),
                        draft=self._to_response(draft),
                    )
        except IntegrityError as exc:
            raise TicketApprovalStateConflictError(
                "This approval decision was already recorded."
            ) from exc
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

    async def list(self) -> list[TicketDraftResponse]:
        await self._ensure_schema()
        try:
            async with self._session_factory() as session:
                result = await session.scalars(
                    select(TicketDraftRow).order_by(
                        TicketDraftRow.created_at.desc()
                    )
                )
                return [self._to_response(row) for row in result.all()]
        except SQLAlchemyError as exc:
            raise TicketPersistenceError() from exc

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
                    await connection.run_sync(TicketBase.metadata.create_all)
                    columns = await connection.exec_driver_sql(
                        "PRAGMA table_info(ticket_drafts)"
                    )
                    column_names = {
                        str(row[1]) for row in columns.fetchall()
                    }
                    if "version" not in column_names:
                        await connection.exec_driver_sql(
                            "ALTER TABLE ticket_drafts "
                            "ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                        )
                self._schema_ready = True
            except SQLAlchemyError as exc:
                raise TicketPersistenceError() from exc

    async def _get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> TicketDraftResponse | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(TicketDraftRow).where(
                    TicketDraftRow.idempotency_key == idempotency_key
                )
            )
            return self._to_response(row) if row is not None else None

    @staticmethod
    def _to_response(row: TicketDraftRow) -> TicketDraftResponse:
        return TicketDraftResponse(
            id=row.id,
            title=row.title,
            description=row.description,
            device_or_system=row.device_or_system,
            status=row.status,
            version=row.version,
            created_at=SQLAlchemyTicketDraftRepository._utc(row.created_at),
            updated_at=SQLAlchemyTicketDraftRepository._utc(row.updated_at),
        )

    @staticmethod
    def _approval_to_record(
        row: TicketApprovalRow,
    ) -> TicketApprovalRecord:
        return TicketApprovalRecord(
            thread_id=row.thread_id,
            draft_id=row.draft_id,
            draft_version=row.draft_version,
            status=row.status,
            note=row.note,
            requested_at=SQLAlchemyTicketDraftRepository._utc(
                row.requested_at
            ),
            decided_at=(
                SQLAlchemyTicketDraftRepository._utc(row.decided_at)
                if row.decided_at is not None
                else None
            ),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(
            tzinfo=timezone.utc
        )

