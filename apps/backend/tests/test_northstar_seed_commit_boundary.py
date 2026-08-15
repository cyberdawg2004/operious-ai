"""Fail-closed proofs for the Northstar durable-commit boundary."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import fields
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, AsyncTransaction

from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.tenant.lifecycle import PostgresTenantLifecycleRepository
from scripts.northstar_demo.commit_reconciliation import (
    NorthstarCommitReconciliationOutcome,
    NorthstarCommitReconciliationResult,
    NorthstarSeedCommitCoordinator,
)
from scripts.northstar_demo.manifest import MANIFEST, NorthstarDemoManifest
from scripts.northstar_demo.seed import (
    NorthstarCommitOutcomeUnknown,
    NorthstarDemoSeedService,
    NorthstarPreDurableCommitRejected,
    NorthstarSeedVerification,
)
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    NorthstarVerificationResult,
    verify_northstar_fixture_read_only,
)
from tests.support.northstar_side_effect_guards import (
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
        await service.create_tenant(tenant_id=tenant_id, created_by="gate-b1d-test")


async def _opened_rollback_session(
    engine: AsyncEngine,
) -> tuple[AsyncConnection, AsyncTransaction, AsyncSession]:
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


@pytest.mark.asyncio
async def test_pre_durable_commit_rejection_rolls_back_without_side_effects(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rejection runs after final COMPLETE_MATCH but before driver commit."""

    import scripts.northstar_demo.seed as seed_module

    sentinel_id = f"gate-b1d-sentinel-{uuid.uuid4().hex}"
    await _create_sentinel(pg_engine, sentinel_id)
    connection, outer, session = await _opened_rollback_session(pg_engine)
    statements: list[str] = []
    classifications: list[NorthstarVerificationClassification] = []
    commit_attempts = 0
    original_verifier = seed_module.verify_northstar_fixture

    async def observing_verifier(
        *args: object, **kwargs: object
    ) -> NorthstarVerificationResult:
        result = await original_verifier(
            cast(AsyncSession, args[0]),
            manifest=cast(NorthstarDemoManifest, kwargs["manifest"]),
        )
        classifications.append(result.classification)
        return result

    async def reject_before_driver_commit() -> None:
        nonlocal commit_attempts
        commit_attempts += 1
        raise NorthstarPreDurableCommitRejected()

    def record_statement(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.split(maxsplit=1)[0].upper())

    event.listen(connection.sync_connection, "before_cursor_execute", record_statement)
    monkeypatch.setattr(seed_module, "verify_northstar_fixture", observing_verifier)
    try:
        with monkeypatch.context() as guard_patch:
            with install_northstar_side_effect_guards(guard_patch) as guard:
                with pytest.raises(NorthstarPreDurableCommitRejected):
                    await NorthstarDemoSeedService(
                        session,
                        pre_durable_commit_hook=reject_before_driver_commit,
                    ).seed()
        assert guard.all_counts_zero
        assert commit_attempts == 1
        assert classifications == [
            NorthstarVerificationClassification.ABSENT,
            NorthstarVerificationClassification.COMPLETE_MATCH,
        ]
        assert "DELETE" not in statements
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", record_statement)
        await session.close()
        await outer.rollback()
        await connection.close()

    await _assert_target_absent(pg_engine)
    async with AsyncSession(pg_engine, expire_on_commit=False) as fresh:
        assert (
            await fresh.execute(
                text("SELECT status FROM tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": sentinel_id},
            )
        ).scalar_one() == "active"


class _TrackedSession:
    def __init__(self) -> None:
        self.close_count = 0

    async def close(self) -> None:
        self.close_count += 1


def _verification_result(
    classification: NorthstarVerificationClassification,
) -> NorthstarVerificationResult:
    return NorthstarVerificationResult(classification, (), (), ())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("classification", "expected"),
    (
        (
            NorthstarVerificationClassification.ABSENT,
            NorthstarCommitReconciliationOutcome.VERIFIED_NOT_COMMITTED,
        ),
        (
            NorthstarVerificationClassification.COMPLETE_MATCH,
            NorthstarCommitReconciliationOutcome.VERIFIED_COMMITTED_COMPLETE,
        ),
        (
            NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH,
            NorthstarCommitReconciliationOutcome.VERIFIED_UNSAFE_STATE,
        ),
    ),
)
async def test_commit_unknown_reconciles_once_without_retry(
    classification: NorthstarVerificationClassification,
    expected: NorthstarCommitReconciliationOutcome,
) -> None:
    sessions = [_TrackedSession(), _TrackedSession()]
    created_sessions = list(sessions)
    seed_calls = 0
    verifier_calls = 0
    commit_attempts = 0

    def session_factory() -> AsyncSession:
        return cast(AsyncSession, sessions.pop(0))

    async def ambiguous_seed(_session: AsyncSession) -> NorthstarSeedVerification:
        nonlocal seed_calls, commit_attempts
        seed_calls += 1
        commit_attempts += 1
        raise NorthstarCommitOutcomeUnknown()

    async def deterministic_verifier(
        _session: AsyncSession, _manifest: NorthstarDemoManifest
    ) -> NorthstarVerificationResult:
        nonlocal verifier_calls
        verifier_calls += 1
        return _verification_result(classification)

    result = await NorthstarSeedCommitCoordinator(
        session_factory,
        seed_operation=ambiguous_seed,
        read_only_verifier=deterministic_verifier,
    ).seed_once()

    assert isinstance(result, NorthstarCommitReconciliationResult)
    assert result.outcome is expected
    assert seed_calls == 1
    assert commit_attempts == 1
    assert verifier_calls == 1
    assert not sessions
    assert [session.close_count for session in created_sessions] == [1, 1]


@pytest.mark.asyncio
async def test_commit_unknown_verifier_error_is_unverifiable_without_retry() -> None:
    sessions = [_TrackedSession(), _TrackedSession()]
    created_sessions = list(sessions)
    seed_calls = 0
    verifier_calls = 0

    def session_factory() -> AsyncSession:
        return cast(AsyncSession, sessions.pop(0))

    async def ambiguous_seed(_session: AsyncSession) -> NorthstarSeedVerification:
        nonlocal seed_calls
        seed_calls += 1
        raise NorthstarCommitOutcomeUnknown()

    async def failing_verifier(
        _session: AsyncSession, _manifest: NorthstarDemoManifest
    ) -> NorthstarVerificationResult:
        nonlocal verifier_calls
        verifier_calls += 1
        raise RuntimeError("driver details must not escape")

    result = await NorthstarSeedCommitCoordinator(
        session_factory,
        seed_operation=ambiguous_seed,
        read_only_verifier=failing_verifier,
    ).seed_once()

    assert isinstance(result, NorthstarCommitReconciliationResult)
    assert result.outcome is NorthstarCommitReconciliationOutcome.OUTCOME_UNVERIFIABLE
    assert seed_calls == 1
    assert verifier_calls == 1
    assert not sessions
    assert [session.close_count for session in created_sessions] == [1, 1]


@pytest.mark.asyncio
async def test_commit_unknown_verifier_timeout_is_unverifiable_without_waiting() -> None:
    sessions = [_TrackedSession(), _TrackedSession()]
    created_sessions = list(sessions)
    seed_calls = 0
    verifier_calls = 0

    def session_factory() -> AsyncSession:
        return cast(AsyncSession, sessions.pop(0))

    async def ambiguous_seed(_session: AsyncSession) -> NorthstarSeedVerification:
        nonlocal seed_calls
        seed_calls += 1
        raise NorthstarCommitOutcomeUnknown()

    async def blocked_verifier(
        _session: AsyncSession, _manifest: NorthstarDemoManifest
    ) -> NorthstarVerificationResult:
        nonlocal verifier_calls
        verifier_calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    result = await NorthstarSeedCommitCoordinator(
        session_factory,
        seed_operation=ambiguous_seed,
        read_only_verifier=blocked_verifier,
        verification_timeout_seconds=0.01,
    ).seed_once()

    assert isinstance(result, NorthstarCommitReconciliationResult)
    assert result.outcome is NorthstarCommitReconciliationOutcome.OUTCOME_UNVERIFIABLE
    assert seed_calls == 1
    assert verifier_calls == 1
    assert not sessions
    assert [session.close_count for session in created_sessions] == [1, 1]


@pytest.mark.asyncio
async def test_commit_unknown_uses_the_real_read_only_verifier(
    pg_engine: AsyncEngine,
) -> None:
    """This proves the ABSENT branch performs no repair or second seed."""

    seed_calls = 0

    def session_factory() -> AsyncSession:
        return AsyncSession(pg_engine, expire_on_commit=False)

    async def ambiguous_seed(_session: AsyncSession) -> NorthstarSeedVerification:
        nonlocal seed_calls
        seed_calls += 1
        raise NorthstarCommitOutcomeUnknown()

    result = await NorthstarSeedCommitCoordinator(
        session_factory,
        seed_operation=ambiguous_seed,
    ).seed_once()

    assert isinstance(result, NorthstarCommitReconciliationResult)
    assert result.outcome is NorthstarCommitReconciliationOutcome.VERIFIED_NOT_COMMITTED
    assert seed_calls == 1
    await _assert_target_absent(pg_engine)


def test_commit_outcomes_are_sanitized_and_seed_path_has_no_retry_loop() -> None:
    result = NorthstarCommitReconciliationResult(
        NorthstarCommitReconciliationOutcome.OUTCOME_UNVERIFIABLE,
        MANIFEST.tenant_id,
    )
    assert [field.name for field in fields(result)] == ["outcome", "tenant_id"]
    assert "driver details" not in str(NorthstarCommitOutcomeUnknown())

    scripts_root = Path(__file__).resolve().parents[1] / "scripts/northstar_demo"
    coordinator_source = (scripts_root / "commit_reconciliation.py").read_text()
    seed_source = (scripts_root / "seed.py").read_text()
    cli_source = (scripts_root / "__main__.py").read_text()
    assert "while " not in coordinator_source
    assert "@retry" not in coordinator_source.casefold()
    assert ".retry(" not in coordinator_source.casefold()
    assert coordinator_source.count("self._seed_operation(") == 1
    assert "NorthstarSeedCommitCoordinator(session_factory).seed_once()" in cli_source
    assert "NorthstarCommitOutcomeUnknown" in seed_source
