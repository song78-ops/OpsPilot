"""Repository interface and SQLAlchemy SQLite implementation."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import DateTime, String, Text, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
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
from app.tickets.exceptions import TicketPersistenceError


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
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

    async def close(self) -> None:
        ...


class SQLAlchemyTicketDraftRepository:
    """SQLite persistence with unique tool-call idempotency."""

    def __init__(self, database_url: str) -> None:
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
                    row = await session.get(TicketDraftRow, draft_id)
                    if row is None:
                        return None
                    if values.title is not None:
                        row.title = values.title
                    if values.description is not None:
                        row.description = values.description
                    if values.device_or_system is not None:
                        row.device_or_system = values.device_or_system
                    row.updated_at = datetime.now(timezone.utc)
                return self._to_response(row)
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
            status="draft",
            created_at=SQLAlchemyTicketDraftRepository._utc(row.created_at),
            updated_at=SQLAlchemyTicketDraftRepository._utc(row.updated_at),
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(
            tzinfo=timezone.utc
        )

