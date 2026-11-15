"""Human-in-the-loop approval tests using real SQLite and LangGraph checkpoints."""

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from app.api.deps import get_approval_service
from app.approvals.runtime import ApprovalRuntime, create_approval_runtime
from app.main import app
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.ticket import CreateTicketDraftArgs, TicketDraftUpdateRequest
from app.tickets.exceptions import (
    ApprovalCheckpointStateError,
    TicketApprovalNotFoundError,
    TicketApprovalMappingMissingError,
    TicketApprovalStateConflictError,
    TicketDraftNotFoundError,
    TicketDraftStateConflictError,
    TicketDraftVersionConflictError,
    TicketPersistenceError,
)
from app.tickets.repository import SQLAlchemyTicketDraftRepository
from app.tickets.service import TicketDraftService


@dataclass(slots=True)
class ApprovalHarness:
    database_path: Path
    checkpoint_path: Path
    repository: SQLAlchemyTicketDraftRepository
    ticket_service: TicketDraftService
    runtime: ApprovalRuntime

    async def close(self) -> None:
        await self.runtime.close()
        await self.repository.close()


async def make_harness(
    tmp_path: Path,
    *,
    database_name: str = "tickets.db",
    checkpoint_name: str = "approval_checkpoints.db",
) -> ApprovalHarness:
    database_path = tmp_path / database_name
    checkpoint_path = tmp_path / checkpoint_name
    repository = SQLAlchemyTicketDraftRepository(
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    runtime = await create_approval_runtime(
        checkpoint_path=checkpoint_path,
        repository=repository,
    )
    return ApprovalHarness(
        database_path=database_path,
        checkpoint_path=checkpoint_path,
        repository=repository,
        ticket_service=TicketDraftService(repository),
        runtime=runtime,
    )


async def seed_draft(
    harness: ApprovalHarness,
    *,
    key: str = "seed-approval",
    title: str = "电脑无法联网",
):
    return await harness.ticket_service.create(
        args=CreateTicketDraftArgs(
            title=title,
            description="办公电脑无法连接公司网络。",
            device_or_system="Windows 笔记本",
        ),
        idempotency_key=key,
    )


def audit_actions(database_path: Path, thread_id: str) -> list[str]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT action FROM ticket_approval_audit "
            "WHERE thread_id = ? ORDER BY id",
            (thread_id,),
        ).fetchall()
    return [str(row[0]) for row in rows]


async def test_request_really_interrupts_and_approve_resumes(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness)
        view = await harness.runtime.service.request(created.draft.id)

        assert view.approval.status == "pending_approval"
        assert view.draft.status == "pending_approval"
        assert view.waiting_for_decision is True
        snapshot = await harness.runtime.service._workflow.get_snapshot(
            view.approval.thread_id
        )
        assert snapshot.next == ("await_decision",)
        assert len(snapshot.interrupts) == 1
        assert snapshot.interrupts[0].value["type"] == "ticket_approval"
        assert snapshot.values["draft_id"] == created.draft.id

        decision = await harness.runtime.service.decide(
            view.approval.thread_id,
            ApprovalDecisionRequest(
                decision="approve",
                note="本地演示审批通过",
            ),
        )

        assert decision.decision == "approve"
        assert decision.transition.approval.status == "approved"
        assert decision.transition.draft.status == "approved"
        assert decision.executed_nodes == [
            "load_draft",
            "await_decision",
            "apply_decision",
        ]
        assert audit_actions(
            harness.database_path,
            view.approval.thread_id,
        ) == ["request", "approve"]
        final_snapshot = (
            await harness.runtime.service._workflow.get_snapshot(
                view.approval.thread_id
            )
        )
        assert final_snapshot.interrupts == ()
        assert final_snapshot.next == ()
    finally:
        await harness.close()


async def test_reject_resumes_and_persists_terminal_state(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="reject")
        waiting = await harness.runtime.service.request(created.draft.id)
        result = await harness.runtime.service.decide(
            waiting.approval.thread_id,
            ApprovalDecisionRequest(decision="reject", note="信息不足"),
        )

        assert result.transition.approval.status == "rejected"
        assert result.transition.approval.note == "信息不足"
        assert result.transition.draft.status == "rejected"
        assert audit_actions(
            harness.database_path,
            waiting.approval.thread_id,
        ) == ["request", "reject"]
    finally:
        await harness.close()


async def test_waiting_approval_survives_restart_and_can_resume(
    tmp_path: Path,
) -> None:
    first = await make_harness(tmp_path)
    created = await seed_draft(first, key="restart")
    waiting = await first.runtime.service.request(created.draft.id)
    thread_id = waiting.approval.thread_id
    await first.close()

    second = await make_harness(tmp_path)
    try:
        restored = await second.runtime.service.get(thread_id)
        assert restored.waiting_for_decision is True
        assert restored.draft.status == "pending_approval"
        snapshot = await second.runtime.service._workflow.get_snapshot(thread_id)
        assert len(snapshot.interrupts) == 1

        decided = await second.runtime.service.decide(
            thread_id,
            ApprovalDecisionRequest(decision="approve"),
        )
        assert decided.transition.draft.status == "approved"
    finally:
        await second.close()


async def test_lookup_approval_by_draft_survives_restart(
    tmp_path: Path,
) -> None:
    first = await make_harness(tmp_path)
    created = await seed_draft(first, key="lookup-recovery")
    before = await first.runtime.service.get_by_draft(created.draft.id)
    assert before.approval is None
    assert before.draft.status == "draft"
    waiting = await first.runtime.service.request(created.draft.id)
    thread_id = waiting.approval.thread_id
    await first.close()

    second = await make_harness(tmp_path)
    try:
        restored = await second.runtime.service.get_by_draft(created.draft.id)
        assert restored.approval is not None
        assert restored.approval.thread_id == thread_id
        assert restored.approval.status == "pending_approval"
        assert restored.waiting_for_decision is True
        assert restored.checkpoint_next == ["await_decision"]

        await second.runtime.service.decide(
            thread_id,
            ApprovalDecisionRequest(decision="approve"),
        )
        completed = await second.runtime.service.get_by_draft(created.draft.id)
        assert completed.approval is not None
        assert completed.approval.status == "approved"
        assert completed.draft.status == "approved"
        assert completed.waiting_for_decision is False
        assert completed.checkpoint_next == []
    finally:
        await second.close()


async def test_lookup_by_draft_distinguishes_not_requested_invalid_and_inconsistent(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        draft = await seed_draft(harness, key="lookup-states")
        not_requested = await harness.runtime.service.get_by_draft(draft.draft.id)
        assert not_requested.approval is None
        assert not_requested.waiting_for_decision is False

        with pytest.raises(TicketDraftNotFoundError):
            await harness.runtime.service.get_by_draft("f" * 32)

        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "UPDATE ticket_drafts SET status = 'pending_approval' "
                "WHERE id = ?",
                (draft.draft.id,),
            )
            connection.commit()
        with pytest.raises(TicketApprovalMappingMissingError):
            await harness.runtime.service.get_by_draft(draft.draft.id)
    finally:
        await harness.close()


async def test_lookup_by_draft_detects_status_and_version_mismatch(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        status_draft = await seed_draft(
            harness,
            key="lookup-status-mismatch",
            title="状态冲突",
        )
        await harness.runtime.service.request(status_draft.draft.id)
        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "UPDATE ticket_drafts SET status = 'approved' WHERE id = ?",
                (status_draft.draft.id,),
            )
            connection.commit()
        with pytest.raises(ApprovalCheckpointStateError):
            await harness.runtime.service.get_by_draft(status_draft.draft.id)

        version_draft = await seed_draft(
            harness,
            key="lookup-version-mismatch",
            title="版本冲突",
        )
        await harness.runtime.service.request(version_draft.draft.id)
        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "UPDATE ticket_drafts SET version = version + 1 WHERE id = ?",
                (version_draft.draft.id,),
            )
            connection.commit()
        with pytest.raises(TicketDraftVersionConflictError):
            await harness.runtime.service.get_by_draft(version_draft.draft.id)
    finally:
        await harness.close()


async def test_duplicate_and_concurrent_decisions_only_apply_once(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="concurrent")
        waiting = await harness.runtime.service.request(created.draft.id)
        thread_id = waiting.approval.thread_id

        results = await asyncio.gather(
            harness.runtime.service.decide(
                thread_id,
                ApprovalDecisionRequest(decision="approve"),
            ),
            harness.runtime.service.decide(
                thread_id,
                ApprovalDecisionRequest(decision="approve"),
            ),
            return_exceptions=True,
        )

        successes = [
            result
            for result in results
            if not isinstance(result, BaseException)
        ]
        conflicts = [
            result
            for result in results
            if isinstance(result, TicketApprovalStateConflictError)
        ]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert audit_actions(harness.database_path, thread_id) == [
            "request",
            "approve",
        ]

        with pytest.raises(TicketApprovalStateConflictError):
            await harness.runtime.service.decide(
                thread_id,
                ApprovalDecisionRequest(decision="reject"),
            )
    finally:
        await harness.close()


async def test_pending_draft_cannot_be_updated_and_version_conflict_blocks_decision(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="version")
        waiting = await harness.runtime.service.request(created.draft.id)

        with pytest.raises(TicketDraftStateConflictError):
            await harness.ticket_service.update(
                created.draft.id,
                TicketDraftUpdateRequest(description="审批中修改"),
            )

        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "UPDATE ticket_drafts SET version = version + 1, "
                "description = ? WHERE id = ?",
                ("绕过 API 修改的内容", created.draft.id),
            )
            connection.commit()

        with pytest.raises(TicketDraftVersionConflictError):
            await harness.runtime.service.decide(
                waiting.approval.thread_id,
                ApprovalDecisionRequest(decision="approve"),
            )
        stored = await harness.ticket_service.get(created.draft.id)
        assert stored.status == "pending_approval"
        assert stored.version == created.draft.version + 1
    finally:
        await harness.close()


async def test_invalid_thread_wrong_state_and_checkpoint_mismatch(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        first = await seed_draft(harness, key="mismatch-a", title="草稿 A")
        second = await seed_draft(harness, key="mismatch-b", title="草稿 B")

        with pytest.raises(TicketApprovalNotFoundError):
            await harness.runtime.service.get("not-a-thread")

        thread_id = "a" * 32
        await harness.runtime.service._workflow.start(
            thread_id=thread_id,
            draft_id=second.draft.id,
        )
        await harness.repository.request_approval(
            draft_id=first.draft.id,
            thread_id=thread_id,
            expected_version=first.draft.version,
        )
        with pytest.raises(ApprovalCheckpointStateError):
            await harness.runtime.service.get(thread_id)
    finally:
        await harness.close()


async def test_request_failure_does_not_leave_orphan_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await make_harness(tmp_path)
    original = harness.repository.request_approval

    async def fail_once(**kwargs):
        raise TicketPersistenceError()

    try:
        created = await seed_draft(harness, key="retry")
        monkeypatch.setattr(harness.repository, "request_approval", fail_once)
        with pytest.raises(TicketPersistenceError):
            await harness.runtime.service.request(created.draft.id)

        with pytest.raises(TicketApprovalNotFoundError):
            await harness.runtime.service.get(
                "0" * 32,
            )

        monkeypatch.setattr(
            harness.repository,
            "request_approval",
            original,
        )
        retried = await harness.runtime.service.request(created.draft.id)
        assert retried.waiting_for_decision is True
        assert retried.draft.status == "pending_approval"
    finally:
        await harness.close()


async def test_interrupt_precedes_business_side_effects(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="side-effect")
        thread_id = "b" * 32
        snapshot = await harness.runtime.service._workflow.start(
            thread_id=thread_id,
            draft_id=created.draft.id,
        )

        assert len(snapshot.interrupts) == 1
        still_draft = await harness.ticket_service.get(created.draft.id)
        assert still_draft.status == "draft"
        assert await harness.repository.get_approval(thread_id) is None
    finally:
        await harness.close()


async def test_duplicate_request_is_rejected(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="duplicate-request")
        first = await harness.runtime.service.request(created.draft.id)
        with pytest.raises(TicketApprovalStateConflictError):
            await harness.runtime.service.request(created.draft.id)
        persisted = await harness.runtime.service.get(first.approval.thread_id)
        assert persisted.waiting_for_decision is True
    finally:
        await harness.close()


async def test_audit_failure_rolls_back_decision_and_retry_recovers(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        created = await seed_draft(harness, key="audit-rollback")
        waiting = await harness.runtime.service.request(created.draft.id)
        thread_id = waiting.approval.thread_id
        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "INSERT INTO ticket_approval_audit "
                "(thread_id, draft_id, action, from_status, to_status, "
                "draft_version, note, created_at) "
                "VALUES (?, ?, 'approve', 'pending_approval', 'approved', "
                "?, NULL, CURRENT_TIMESTAMP)",
                (thread_id, created.draft.id, created.draft.version),
            )
            connection.commit()

        with pytest.raises(TicketApprovalStateConflictError):
            await harness.runtime.service.decide(
                thread_id,
                ApprovalDecisionRequest(decision="approve"),
            )
        pending = await harness.ticket_service.get(created.draft.id)
        assert pending.status == "pending_approval"
        mapping = await harness.repository.get_approval(thread_id)
        assert mapping is not None
        assert mapping.status == "pending_approval"

        with sqlite3.connect(harness.database_path) as connection:
            connection.execute(
                "DELETE FROM ticket_approval_audit "
                "WHERE thread_id = ? AND action = 'approve'",
                (thread_id,),
            )
            connection.commit()

        recovered = await harness.runtime.service.decide(
            thread_id,
            ApprovalDecisionRequest(decision="approve"),
        )
        assert recovered.transition.draft.status == "approved"
        assert audit_actions(harness.database_path, thread_id) == [
            "request",
            "approve",
        ]
    finally:
        await harness.close()


async def test_checkpointer_uses_restricted_deserialization(
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    try:
        serializer = harness.runtime.checkpointer.serde
        assert serializer.pickle_fallback is False
        assert serializer._allowed_msgpack_modules is None
        assert serializer._allowed_json_modules is None
    finally:
        await harness.close()


async def test_existing_ticket_database_gets_version_migration(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-tickets.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE ticket_drafts ("
            "id VARCHAR(32) PRIMARY KEY, "
            "idempotency_key VARCHAR(128) NOT NULL UNIQUE, "
            "title VARCHAR(200) NOT NULL, "
            "description TEXT NOT NULL, "
            "device_or_system VARCHAR(200) NOT NULL, "
            "status VARCHAR(20) NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        connection.commit()

    repository = SQLAlchemyTicketDraftRepository(
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    try:
        assert await repository.list() == []
        with sqlite3.connect(database_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(ticket_drafts)"
                ).fetchall()
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
        assert "version" in columns
        assert "ticket_approvals" in tables
        assert "ticket_approval_audit" in tables
    finally:
        await repository.close()


async def test_approval_api_request_get_and_decision(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    app.dependency_overrides[get_approval_service] = (
        lambda: harness.runtime.service
    )
    try:
        created = await seed_draft(harness, key="api")
        request_response = await client.post(
            f"/api/v1/tickets/drafts/{created.draft.id}/request-approval"
        )
        assert request_response.status_code == 202
        body = request_response.json()
        thread_id = body["approval"]["thread_id"]
        assert body["waiting_for_decision"] is True
        assert body["checkpoint_next"] == ["await_decision"]

        get_response = await client.get(
            f"/api/v1/agent/approvals/{thread_id}"
        )
        assert get_response.status_code == 200
        assert get_response.json()["draft"]["status"] == "pending_approval"

        decision_response = await client.post(
            f"/api/v1/agent/approvals/{thread_id}/decision",
            json={"decision": "approve", "note": "Swagger 本地审批"},
        )
        assert decision_response.status_code == 200
        decided = decision_response.json()
        assert decided["approval"]["status"] == "approved"
        assert decided["draft"]["status"] == "approved"
        assert decided["executed_nodes"] == [
            "load_draft",
            "await_decision",
            "apply_decision",
        ]

        repeated = await client.post(
            f"/api/v1/agent/approvals/{thread_id}/decision",
            json={"decision": "reject"},
        )
        assert repeated.status_code == 409
        assert (
            repeated.json()["error"]["code"]
            == "TICKET_APPROVAL_STATE_CONFLICT"
        )
    finally:
        await harness.close()


async def test_draft_approval_lookup_api_recovers_without_local_mapping(
    client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    harness = await make_harness(tmp_path)
    app.dependency_overrides[get_approval_service] = (
        lambda: harness.runtime.service
    )
    try:
        created = await seed_draft(harness, key="lookup-api")
        before = await client.get(
            f"/api/v1/tickets/drafts/{created.draft.id}/approval"
        )
        assert before.status_code == 200
        assert before.json()["status"] == "not_requested"
        assert before.json()["approval"] is None

        requested = await client.post(
            f"/api/v1/tickets/drafts/{created.draft.id}/request-approval"
        )
        assert requested.status_code == 202
        thread_id = requested.json()["approval"]["thread_id"]

        pending = await client.get(
            f"/api/v1/tickets/drafts/{created.draft.id}/approval"
        )
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending_approval"
        assert pending.json()["approval"]["thread_id"] == thread_id
        assert pending.json()["waiting_for_decision"] is True
        assert pending.json()["checkpoint_next"] == ["await_decision"]

        decision = await client.post(
            f"/api/v1/agent/approvals/{thread_id}/decision",
            json={"decision": "reject", "note": "按草稿查询恢复后拒绝"},
        )
        assert decision.status_code == 200

        completed = await client.get(
            f"/api/v1/tickets/drafts/{created.draft.id}/approval"
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "rejected"
        assert completed.json()["draft"]["status"] == "rejected"
        assert completed.json()["waiting_for_decision"] is False

        missing = await client.get(
            f"/api/v1/tickets/drafts/{'f' * 32}/approval"
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "TICKET_DRAFT_NOT_FOUND"
    finally:
        await harness.close()
