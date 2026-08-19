"""Strict verifier regressions on the production-compatible local schema."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import nullcontext

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from scripts.northstar_demo.manifest import MANIFEST
from scripts.northstar_demo.seed import NorthstarDemoSeedService
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture,
    verify_northstar_fixture_read_only,
)


async def _assert_0104_compatibility(session: AsyncSession) -> None:
    revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    ladder_exists = (await session.execute(text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL"))).scalar_one()
    assert revision == "0104_connector_credentials_rls"
    assert ladder_exists is False


async def _target_snapshot(session: AsyncSession) -> tuple[int, int, int, int]:
    values = await session.execute(
        text(
            "SELECT "
            "(SELECT count(*) FROM tenants WHERE tenant_id = :tenant_id), "
            "(SELECT count(*) FROM operational_sessions WHERE session_id = :session_id), "
            "(SELECT count(*) FROM resolution_proposals WHERE proposal_id = :proposal_id), "
            "(SELECT count(*) FROM action_approval_records WHERE approval_id = :approval_id)"
        ),
        {
            "tenant_id": MANIFEST.tenant_id,
            "session_id": str(MANIFEST.session_id),
            "proposal_id": str(MANIFEST.proposal_id),
            "approval_id": str(MANIFEST.approval_id),
        },
    )
    return tuple(int(value) for value in values.one())  # type: ignore[return-value]


@pytest.fixture
async def complete_fixture(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    connection = await pg_engine.connect()
    guard_session = AsyncSession(bind=connection, expire_on_commit=False)
    session: AsyncSession | None = None
    transaction = None
    try:
        await _assert_0104_compatibility(guard_session)
        await guard_session.rollback()
        await guard_session.close()
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        assert (await NorthstarDemoSeedService(session).seed()).state == "complete"
        yield session
    finally:
        await guard_session.close()
        if session is not None:
            await session.close()
        if transaction is not None:
            await transaction.rollback()
        await connection.close()


@pytest.mark.asyncio
async def test_absent_is_read_only_and_complete_is_idempotent(
    pg_engine: AsyncEngine, complete_fixture: AsyncSession
) -> None:
    absent_session = AsyncSession(pg_engine, expire_on_commit=False)
    try:
        await _assert_0104_compatibility(absent_session)
        await absent_session.rollback()
        # The rollback-only complete fixture is on another connection.
        before_snapshot = await _target_snapshot(absent_session)
        await absent_session.rollback()
        absent = await verify_northstar_fixture_read_only(absent_session, manifest=MANIFEST)
        after_snapshot = await _target_snapshot(absent_session)
        assert absent.classification is NorthstarVerificationClassification.ABSENT
        assert before_snapshot == after_snapshot == (0, 0, 0, 0)
    finally:
        await absent_session.close()

    before = (set(complete_fixture.new), set(complete_fixture.dirty), set(complete_fixture.deleted))
    result = await verify_northstar_fixture(complete_fixture, manifest=MANIFEST)
    after = (set(complete_fixture.new), set(complete_fixture.dirty), set(complete_fixture.deleted))
    assert result.classification is NorthstarVerificationClassification.COMPLETE_MATCH
    assert result.reason_codes == ()
    assert all(count == 0 for _, count in result.forbidden_counts)
    assert before == after == (set(), set(), set())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("DELETE FROM session_events WHERE session_id = :session_id AND sequence = 0", "session_timeline_mismatch"),
        ("DELETE FROM session_events WHERE session_id = :session_id AND sequence = 1", "session_timeline_mismatch"),
        ("DELETE FROM session_events WHERE session_id = :session_id AND sequence = 2", "session_timeline_mismatch"),
        ("UPDATE session_events SET kind = 'customer_message' WHERE session_id = :session_id AND sequence = 2", "session_timeline_mismatch"),
        ("UPDATE operational_sessions SET sequence_head = 1 WHERE session_id = :session_id", "session_mismatch"),
        ("UPDATE operational_sessions SET sequence_head = 3 WHERE session_id = :session_id", "session_mismatch"),
        ("UPDATE resolution_proposals SET status = 'denied' WHERE proposal_id = :proposal_id", "proposal_mismatch"),
        ("UPDATE action_approval_records SET tool_name = 'other.action' WHERE approval_id = :approval_id", "approval_mismatch"),
        ("UPDATE action_approval_records SET status = 'approved' WHERE approval_id = :approval_id", "approval_mismatch"),
        ("UPDATE governance_decisions SET stage = 'other' WHERE decision_id = :decision_id", "governance_mismatch"),
        ("UPDATE supervisor_inspections SET inspection_mode = 'other' WHERE inspection_id = :inspection_id", "inspection_mismatch"),
        ("DELETE FROM qa_score_records WHERE score_id = :score_id", "qa_score_mismatch"),
    ],
)
async def test_expected_fixture_mismatches_fail_closed(
    complete_fixture: AsyncSession, statement: str, reason: str
) -> None:
    params = {
        "session_id": str(MANIFEST.session_id),
        "proposal_id": str(MANIFEST.proposal_id),
        "approval_id": str(MANIFEST.approval_id),
        "decision_id": str(MANIFEST.governance_decision_id),
        "inspection_id": str(MANIFEST.inspection_id),
        "score_id": str(MANIFEST.qa_score_id),
    }
    await complete_fixture.execute(text(statement), params)
    result = await verify_northstar_fixture(complete_fixture, manifest=MANIFEST)
    assert result.classification is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
    assert reason in result.reason_codes


@pytest.mark.asyncio
async def test_malformed_envelope_and_forbidden_resources_fail_closed(
    complete_fixture: AsyncSession,
) -> None:
    await complete_fixture.execute(
        text("UPDATE session_events SET payload = '{}'::jsonb WHERE session_id = :session_id AND sequence = 2"),
        {"session_id": str(MANIFEST.session_id)},
    )
    malformed = await verify_northstar_fixture(complete_fixture, manifest=MANIFEST)
    assert malformed.classification is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
    assert "session_timeline_mismatch" in malformed.reason_codes

    await complete_fixture.execute(
        text("INSERT INTO connector_credentials (tenant_id, connector_id, credentials_enc, credential_hash, configured_by, source_approval_id) VALUES (:tenant_id, 'synthetic', '\\x00'::bytea, :credential_hash, 'test', 'test')"),
        {"tenant_id": MANIFEST.tenant_id, "credential_hash": "0" * 64},
    )
    forbidden = await verify_northstar_fixture(complete_fixture, manifest=MANIFEST)
    assert forbidden.classification is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
    assert "forbidden_resource_present" in forbidden.reason_codes


@pytest.mark.asyncio
async def test_core_emits_only_reads_after_fixture_setup(
    complete_fixture: AsyncSession,
) -> None:
    statements: list[str] = []

    def capture(*args: object) -> None:
        statements.append(str(args[2]).strip().upper())

    event.listen(complete_fixture.bind.sync_engine, "before_cursor_execute", capture)  # type: ignore[union-attr]
    try:
        result = await verify_northstar_fixture(complete_fixture, manifest=MANIFEST)
    finally:
        event.remove(complete_fixture.bind.sync_engine, "before_cursor_execute", capture)  # type: ignore[union-attr]
    assert result.classification is NorthstarVerificationClassification.COMPLETE_MATCH
    forbidden = ("INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "FOR UPDATE")
    assert all(not sql.startswith(forbidden) and " FOR UPDATE" not in sql for sql in statements)


@pytest.mark.asyncio
async def test_repository_error_fails_closed() -> None:
    class FailingSession:
        no_autoflush = nullcontext()

        async def get(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic repository failure")

    result = await verify_northstar_fixture(FailingSession(), manifest=MANIFEST)  # type: ignore[arg-type]
    assert result.classification is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
    assert result.reason_codes == ("repository_error",)
