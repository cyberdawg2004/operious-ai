"""Real PostgreSQL rollback proofs for the Northstar seed transaction."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.tenant.lifecycle import PostgresTenantLifecycleRepository
from app.supervisor.persistence import PostgresSupervisorRepository
from scripts.northstar_demo.manifest import MANIFEST, NorthstarDemoManifest
from scripts.northstar_demo.seed import (
    NorthstarDemoSeedService,
    SeedInjectedFailure,
    SeedStage,
)
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    NorthstarVerificationResult,
    verify_northstar_fixture_read_only,
)


async def _assert_0104(session: AsyncSession) -> None:
    assert (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "0104_connector_credentials_rls"
    assert (await session.execute(text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL"))).scalar_one() is False


async def _target_counts(session: AsyncSession) -> tuple[int, ...]:
    row = (await session.execute(text("""
        SELECT
          (SELECT count(*) FROM tenants WHERE tenant_id = :tenant_id),
          (SELECT count(*) FROM operational_events WHERE tenant_id = :tenant_id),
          (SELECT count(*) FROM operational_sessions WHERE session_id = :session_id),
          (SELECT count(*) FROM session_events WHERE session_id = :session_id),
          (SELECT count(*) FROM governance_decisions WHERE decision_id = :decision_id),
          (SELECT count(*) FROM governance_traces WHERE decision_id = :decision_id),
          (SELECT count(*) FROM resolution_proposals WHERE proposal_id = :proposal_id),
          (SELECT count(*) FROM action_approval_records WHERE approval_id = :approval_id),
          (SELECT count(*) FROM supervisor_inspections WHERE inspection_id = :inspection_id),
          (SELECT count(*) FROM qa_score_records WHERE score_id = :score_id)
    """), {
        "tenant_id": MANIFEST.tenant_id,
        "session_id": str(MANIFEST.session_id),
        "decision_id": str(MANIFEST.governance_decision_id),
        "proposal_id": str(MANIFEST.proposal_id),
        "approval_id": str(MANIFEST.approval_id),
        "inspection_id": str(MANIFEST.inspection_id),
        "score_id": str(MANIFEST.qa_score_id),
    })).one()
    return tuple(int(value) for value in row)


async def _create_sentinel(engine: AsyncEngine, tenant_id: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await _assert_0104(session)
        service = TenantLifecycleService(
            repository=PostgresTenantLifecycleRepository(session),
            event_appender=OperationalEventAppender(
                persistence=PostgresOperationalEventPersistence(session)
            ),
            session=session,
        )
        await service.create_tenant(tenant_id=tenant_id, created_by="gate-b1-test")


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", list(SeedStage))
async def test_each_seed_failpoint_rolls_back_all_target_state(
    pg_engine: AsyncEngine, stage: SeedStage
) -> None:
    sentinel_id = f"gate-b1-sentinel-{uuid.uuid4().hex}"
    await _create_sentinel(pg_engine, sentinel_id)
    async with AsyncSession(pg_engine, expire_on_commit=False) as seed_session:
        await _assert_0104(seed_session)
        await seed_session.rollback()
        service = NorthstarDemoSeedService(
            seed_session, failure_injector=lambda actual: actual is stage
        )
        with pytest.raises(SeedInjectedFailure, match=stage.value):
            await service.seed()

    async with AsyncSession(pg_engine, expire_on_commit=False) as fresh:
        await _assert_0104(fresh)
        await fresh.rollback()
        result = await verify_northstar_fixture_read_only(fresh, manifest=MANIFEST)
        assert result.classification is NorthstarVerificationClassification.ABSENT
        assert await _target_counts(fresh) == (0,) * 10
        sentinel = (await fresh.execute(text("SELECT status FROM tenants WHERE tenant_id = :tenant_id"), {"tenant_id": sentinel_id})).scalar_one()
        assert sentinel == "active"


@pytest.mark.asyncio
async def test_lifecycle_in_transaction_does_not_commit_or_rollback_caller(
    pg_engine: AsyncEngine,
) -> None:
    tenant_id = f"gate-b1-lifecycle-{uuid.uuid4().hex}"
    connection = await pg_engine.connect()
    outer = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    try:
        service = TenantLifecycleService(
            repository=PostgresTenantLifecycleRepository(session),
            event_appender=OperationalEventAppender(persistence=PostgresOperationalEventPersistence(session)),
            session=session,
        )
        await service.create_tenant_in_transaction(tenant_id=tenant_id, created_by="gate-b1-test")
        assert outer.is_active
        await session.flush()
    finally:
        await session.close()
        await outer.rollback()
        await connection.close()
    async with AsyncSession(pg_engine) as fresh:
        assert (await fresh.execute(text("SELECT count(*) FROM tenants WHERE tenant_id = :tenant_id"), {"tenant_id": tenant_id})).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ("lifecycle", "repository", "constraint", "verifier_mismatch", "verifier_error"))
async def test_genuine_seed_failures_roll_back_target_state(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    """Failures originate at real seed boundaries after transaction ownership begins."""
    import scripts.northstar_demo.seed as seed_module

    original_verifier = seed_module.verify_northstar_fixture
    if failure_kind == "lifecycle":
        async def fail_lifecycle(*args: object, **kwargs: object) -> object:
            raise RuntimeError("lifecycle boundary failure")
        monkeypatch.setattr(seed_module.TenantLifecycleService, "create_tenant_in_transaction", fail_lifecycle)
    elif failure_kind == "repository":
        async def fail_repository(*args: object, **kwargs: object) -> object:
            raise RuntimeError("repository boundary failure")
        monkeypatch.setattr(seed_module.PostgresSupervisorRepository, "record_inspection", fail_repository)
    elif failure_kind == "constraint":
        async def fail_constraint(self: PostgresSupervisorRepository, *args: object, **kwargs: object) -> object:
            await self.session.execute(text("INSERT INTO tenants (tenant_id, status) VALUES ('gate-b1-invalid', 'invalid')"))
            return None
        monkeypatch.setattr(seed_module.PostgresSupervisorRepository, "record_inspection", fail_constraint)
    else:
        calls = 0
        async def final_verifier(*args: object, **kwargs: object) -> NorthstarVerificationResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                return await original_verifier(
                    cast(AsyncSession, args[0]),
                    manifest=cast(NorthstarDemoManifest, kwargs["manifest"]),
                )
            if failure_kind == "verifier_error":
                raise RuntimeError("verifier repository error")
            return NorthstarVerificationResult(NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH, ("repository_error",), (), ())
        monkeypatch.setattr(seed_module, "verify_northstar_fixture", final_verifier)

    async with AsyncSession(pg_engine, expire_on_commit=False) as seed_session:
        await _assert_0104(seed_session)
        await seed_session.rollback()
        with pytest.raises(Exception):
            await NorthstarDemoSeedService(seed_session).seed()
    async with AsyncSession(pg_engine, expire_on_commit=False) as fresh:
        await _assert_0104(fresh)
        await fresh.rollback()
        assert (await verify_northstar_fixture_read_only(fresh, manifest=MANIFEST)).classification is NorthstarVerificationClassification.ABSENT
        assert await _target_counts(fresh) == (0,) * 10
