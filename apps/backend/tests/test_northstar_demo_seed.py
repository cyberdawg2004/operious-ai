"""Pure safety-contract tests for the local Northstar demo operator path."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models.timeline import TimelineEvent
from app.session.identity import SessionId
from app.session.models.timeline_event import SessionTimelineEvent
from app.session.persistence import PostgresSessionPersistence, SessionEventQuery
from scripts.northstar_demo.__main__ import PRODUCTION_INTERLOCK, build_parser
from scripts.northstar_demo.manifest import (
    MANIFEST,
    SEEDED_SESSION_SEQUENCE_HEAD,
    SESSION_ID,
    TENANT_ID,
    stable_id,
)
from scripts.northstar_demo.seed import NorthstarDemoSeedService, NorthstarSeedSafetyError
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture_read_only,
)


async def _assert_0104_northstar_compatibility(session: AsyncSession) -> None:
    """Fail closed before a rollback-only Northstar integration fixture."""

    from sqlalchemy import text

    revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    ladder_exists = (await session.execute(text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL"))).scalar_one()
    assert revision == "0104_connector_credentials_rls"
    assert ladder_exists is False


def test_manifest_is_deterministic_and_synthetic_only() -> None:
    assert MANIFEST.tenant_id == TENANT_ID
    assert MANIFEST.session_id == SESSION_ID
    assert MANIFEST.customer_name == "Maya Chen"
    assert MANIFEST.customer_email == "maya.chen@example.com"
    assert SEEDED_SESSION_SEQUENCE_HEAD == 2
    assert stable_id("resolution-proposal") == MANIFEST.proposal_id
    assert isinstance(MANIFEST.approval_id, uuid.UUID)


def test_cli_requires_an_explicit_read_only_or_execute_mode() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
    args = build_parser().parse_args(["--dry-run"])
    assert args.dry_run is True
    assert args.verify is False
    assert args.execute is False
    assert args.tenant_id == TENANT_ID


def test_cli_rejects_any_other_tenant() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--tenant-id", "another-tenant"])


def test_production_interlock_is_a_fixed_literal() -> None:
    assert PRODUCTION_INTERLOCK == "NORTHSTAR_DEMO_PRODUCTION_EXECUTION_AUTHORIZED"


def test_seed_requires_a_fresh_transaction_owner() -> None:
    class _Session:
        def in_transaction(self) -> bool:
            return True

    service = NorthstarDemoSeedService(_Session())  # type: ignore[arg-type]
    with pytest.raises(NorthstarSeedSafetyError, match="fresh session"):
        import asyncio
        asyncio.run(service.seed())


@pytest.mark.asyncio
async def test_seed_is_atomic_and_idempotent_in_an_isolated_database(pg_engine: AsyncEngine) -> None:
    """The fixture uses real repositories but the outer test transaction rolls back."""
    connection = await pg_engine.connect()
    guard_session = AsyncSession(bind=connection, expire_on_commit=False)
    await _assert_0104_northstar_compatibility(guard_session)
    await guard_session.rollback()
    await guard_session.close()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        service = NorthstarDemoSeedService(session)
        created = await service.seed()
        assert created.state == "complete"
        assert (await service.verify()).state == "complete"
        events = await PostgresSessionPersistence(session).list_events(
            SessionEventQuery(session_id=SessionId(SESSION_ID), limit=10, offset=0),
            expected_tenant_id=TENANT_ID,
        )
        assert events.total == 3
        assert [event.sequence for event in events.events] == [0, 1, 2]
        assert (
            await session.execute(
                text(
                    "SELECT sequence_head FROM operational_sessions "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": str(MANIFEST.session_id)},
            )
        ).scalar_one() == SEEDED_SESSION_SEQUENCE_HEAD
        proposal_event = TimelineEvent.from_session_event(
            cast(SessionTimelineEvent, events.events[2]), fallback_tenant_id=TENANT_ID
        )
        assert proposal_event.event_type == "resolution_proposal_created"
        assert proposal_event.payload["proposal_id"] == str(MANIFEST.proposal_id)
        assert proposal_event.payload["status"] == "pending_human_approval"
        assert proposal_event.payload["proposed_customer_reply"]
        assert proposal_event.payload["recommended_actions"] == [
            {
                "type": "replacement.order",
                "label": "Review proposed replacement",
                "requires_execution": True,
            }
        ]
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest.mark.asyncio
async def test_head_one_fixture_is_unsafe_and_never_repaired(
    pg_engine: AsyncEngine,
) -> None:
    """A historical sequence-head mismatch is preserved for manual recovery."""

    connection = await pg_engine.connect()
    outer = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        assert (await NorthstarDemoSeedService(session).seed()).state == "complete"
        await session.execute(
            text(
                "UPDATE operational_sessions SET sequence_head = 1 "
                "WHERE session_id = :session_id"
            ),
            {"session_id": str(MANIFEST.session_id)},
        )
        await session.commit()
        with pytest.raises(NorthstarSeedSafetyError, match="immutable manifest"):
            await NorthstarDemoSeedService(session).seed()
        await session.rollback()
        head = (
            await session.execute(
                text(
                    "SELECT sequence_head FROM operational_sessions "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": str(MANIFEST.session_id)},
            )
        ).scalar_one()
        assert head == 1
        await session.rollback()
        assert (
            await verify_northstar_fixture_read_only(
                session, manifest=MANIFEST
            )
        ).classification is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
    finally:
        await session.close()
        await outer.rollback()
        await connection.close()
