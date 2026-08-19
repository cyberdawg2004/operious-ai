"""Runtime side-effect isolation proofs for the transactional Northstar seed."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    AsyncTransaction,
)

from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.supervisor.persistence import PostgresSupervisorRepository
from app.tenant.lifecycle import PostgresTenantLifecycleRepository
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
from tests.support.northstar_side_effect_guards import (
    BOUNDARY_INVENTORY,
    install_northstar_side_effect_guards,
)


async def _assert_0104(session: AsyncSession) -> None:
    assert (
        await session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0104_connector_credentials_rls"
    assert (
        await session.execute(
            text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL")
        )
    ).scalar_one() is False


async def _target_counts(session: AsyncSession) -> tuple[int, ...]:
    row = (
        await session.execute(
            text(
                """
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
                """
            ),
            {
                "tenant_id": MANIFEST.tenant_id,
                "session_id": str(MANIFEST.session_id),
                "decision_id": str(MANIFEST.governance_decision_id),
                "proposal_id": str(MANIFEST.proposal_id),
                "approval_id": str(MANIFEST.approval_id),
                "inspection_id": str(MANIFEST.inspection_id),
                "score_id": str(MANIFEST.qa_score_id),
            },
        )
    ).one()
    return tuple(int(value) for value in row)


async def _assert_target_absent(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as fresh:
        await _assert_0104(fresh)
        await fresh.rollback()
        result = await verify_northstar_fixture_read_only(fresh, manifest=MANIFEST)
        assert result.classification is NorthstarVerificationClassification.ABSENT
        assert await _target_counts(fresh) == (0,) * 10


async def _create_sentinel(engine: AsyncEngine, tenant_id: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = TenantLifecycleService(
            repository=PostgresTenantLifecycleRepository(session),
            event_appender=OperationalEventAppender(
                persistence=PostgresOperationalEventPersistence(session)
            ),
            session=session,
        )
        await service.create_tenant(tenant_id=tenant_id, created_by="gate-b1c-test")


async def _opened_rollback_session(
    engine: AsyncEngine,
) -> tuple[AsyncConnection, AsyncTransaction, AsyncSession]:
    """Open the only allowed I/O destination before arming the socket guard."""

    connection = await engine.connect()
    outer = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    await _assert_0104(session)
    await session.rollback()
    return connection, outer, session


async def _rollback_opened_session(
    connection: AsyncConnection, outer: AsyncTransaction, session: AsyncSession
) -> None:
    await session.close()
    await outer.rollback()
    await connection.close()


def test_boundary_inventory_is_complete_and_test_only() -> None:
    expected_categories = {
        "Celery task publication",
        "broker/event publication",
        "HTTP clients",
        "raw network connections",
        "connector resolution",
        "connector invocation",
        "credential loading/decryption",
        "provider/client construction",
        "email/message delivery",
        "outbound dispatch",
        "webhook dispatch",
        "fulfillment/action execution",
        "internal receipt executor",
        "work-order publication",
        "retry/reconciliation scheduling",
        "dead-letter publication",
        "escalation publication",
    }
    assert {item.category for item in BOUNDARY_INVENTORY} == expected_categories
    assert all(item.classification == "RUNTIME_GUARD_INSTALLED" for item in BOUNDARY_INVENTORY)

    backend_root = Path(__file__).resolve().parents[1]
    guard_module = "northstar_side_effect_guards"
    production_sources = (backend_root / "app").rglob("*.py")
    assert all(guard_module not in source.read_text() for source in production_sources)


@pytest.mark.asyncio
async def test_complete_construction_is_side_effect_free_and_rolled_back(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection, outer, session = await _opened_rollback_session(pg_engine)
    try:
        with monkeypatch.context() as guard_patch:
            with install_northstar_side_effect_guards(guard_patch) as guard:
                result = await NorthstarDemoSeedService(session).seed()
        assert result.state == "complete"
        assert guard.all_counts_zero
    finally:
        await _rollback_opened_session(connection, outer, session)
    await _assert_target_absent(pg_engine)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", list(SeedStage))
async def test_all_seed_failpoints_are_side_effect_free(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, stage: SeedStage
) -> None:
    sentinel_id = f"gate-b1c-sentinel-{uuid.uuid4().hex}"
    await _create_sentinel(pg_engine, sentinel_id)
    connection, outer, session = await _opened_rollback_session(pg_engine)
    try:
        with monkeypatch.context() as guard_patch:
            with install_northstar_side_effect_guards(guard_patch) as guard:
                with pytest.raises(SeedInjectedFailure, match=stage.value):
                    await NorthstarDemoSeedService(
                        session, failure_injector=lambda actual: actual is stage
                    ).seed()
        assert guard.all_counts_zero
    finally:
        await _rollback_opened_session(connection, outer, session)

    await _assert_target_absent(pg_engine)
    async with AsyncSession(pg_engine, expire_on_commit=False) as fresh:
        assert (
            await fresh.execute(
                text("SELECT status FROM tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": sentinel_id},
            )
        ).scalar_one() == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_kind",
    ("lifecycle", "repository", "constraint", "verifier_mismatch", "verifier_error"),
)
async def test_genuine_seed_failures_are_side_effect_free(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    sentinel_id = f"gate-b1c-genuine-sentinel-{uuid.uuid4().hex}"
    await _create_sentinel(pg_engine, sentinel_id)

    import scripts.northstar_demo.seed as seed_module

    original_verifier = seed_module.verify_northstar_fixture
    if failure_kind == "lifecycle":

        async def fail_lifecycle(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("lifecycle boundary failure")

        monkeypatch.setattr(
            seed_module.TenantLifecycleService,
            "create_tenant_in_transaction",
            fail_lifecycle,
        )
    elif failure_kind == "repository":

        async def fail_repository(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("repository boundary failure")

        monkeypatch.setattr(
            seed_module.PostgresSupervisorRepository,
            "record_inspection",
            fail_repository,
        )
    elif failure_kind == "constraint":

        async def fail_constraint(
            self: PostgresSupervisorRepository,
            *_args: object,
            **_kwargs: object,
        ) -> object:
            await self.session.execute(
                text("INSERT INTO tenants (tenant_id, status) VALUES ('gate-b1c-invalid', 'invalid')")
            )
            return None

        monkeypatch.setattr(
            seed_module.PostgresSupervisorRepository,
            "record_inspection",
            fail_constraint,
        )
    else:
        calls = 0

        async def final_verifier(
            *args: object, **kwargs: object
        ) -> NorthstarVerificationResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                return await original_verifier(
                    cast(AsyncSession, args[0]),
                    manifest=cast(NorthstarDemoManifest, kwargs["manifest"]),
                )
            if failure_kind == "verifier_error":
                raise RuntimeError("verifier repository error")
            return NorthstarVerificationResult(
                NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH,
                ("repository_error",),
                (),
                (),
            )

        monkeypatch.setattr(seed_module, "verify_northstar_fixture", final_verifier)

    connection, outer, session = await _opened_rollback_session(pg_engine)
    try:
        with monkeypatch.context() as guard_patch:
            with install_northstar_side_effect_guards(guard_patch) as guard:
                with pytest.raises(Exception):
                    await NorthstarDemoSeedService(session).seed()
        assert guard.all_counts_zero
    finally:
        await _rollback_opened_session(connection, outer, session)

    await _assert_target_absent(pg_engine)
    async with AsyncSession(pg_engine, expire_on_commit=False) as fresh:
        assert (
            await fresh.execute(
                text("SELECT status FROM tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": sentinel_id},
            )
        ).scalar_one() == "active"


def test_guards_do_not_activate_from_runtime_configuration() -> None:
    """Guards have no production import or configuration activation path."""

    backend_root = Path(__file__).resolve().parents[1]
    seed_source = (backend_root / "scripts/northstar_demo/seed.py").read_text()
    assert "northstar_side_effect_guards" not in seed_source
    assert "UnexpectedNorthstarSideEffect" not in seed_source
