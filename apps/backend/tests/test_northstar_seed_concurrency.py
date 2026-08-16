"""Gate B2 proofs for transaction-scoped Northstar seed serialization.

These tests deliberately require a fresh disposable PostgreSQL database.  The
successful commits are real so two independent backend connections can observe
each other; the test runner drops that exact database after this Gate.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from app.db.test_target import validate_local_postgres_test_target
from scripts.northstar_demo import locking
from scripts.northstar_demo.manifest import MANIFEST
from scripts.northstar_demo.seed import (
    NorthstarConcurrentExecutionBusy,
    NorthstarDemoSeedService,
    NorthstarSeedSafetyError,
    SeedInjectedFailure,
    SeedStage,
)
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture_read_only,
)
from tests.conftest import requires_postgres
from tests.support.northstar_side_effect_guards import (
    SideEffectGuard,
    install_northstar_side_effect_guards,
)


_DISPOSABLE_PREFIX = "operious_northstar_concurrency_test_"
_FORBIDDEN_DATABASES = frozenset(
    {"postgres", "operious", "operious_test", "operious_schema_compat_test"}
)


def _quote_identifier(value: str) -> str:
    return f'"{value.replace('"', '""')}"'


@pytest_asyncio.fixture
async def northstar_disposable_pg_engine(
    pg_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine]:
    """Clone the migrated shared test target and drop the exact clone after Gate."""

    del pg_engine
    test_url = os.environ["TEST_DATABASE_URL"]
    source_target = validate_local_postgres_test_target(test_url)
    database_name = f"{_DISPOSABLE_PREFIX}{uuid.uuid4().hex[:24]}"
    database_url = make_url(test_url).set(database=database_name)
    admin_url = make_url(test_url).set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    disposable_engine = create_async_engine(database_url)
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "CREATE DATABASE "
                    f"{_quote_identifier(database_name)} "
                    "TEMPLATE "
                    f"{_quote_identifier(source_target.database_name)}"
                )
            )
        yield disposable_engine
    finally:
        await disposable_engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name "
                    "AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(
                text(f"DROP DATABASE IF EXISTS {_quote_identifier(database_name)}")
            )
        await admin_engine.dispose()


def test_advisory_key_is_deterministic_and_signed() -> None:
    key = locking.derive_northstar_seed_lock_key("northstar-clueso-demo")
    assert key == locking.derive_northstar_seed_lock_key("northstar-clueso-demo")
    assert -(2**63) <= key <= 2**63 - 1
    assert key != locking.derive_northstar_seed_lock_key("northstar-clueso-demo-2")
    for noncanonical in ("Northstar-Clueso-Demo", "northstar-clueso-demo ", ""):
        with pytest.raises(locking.NorthstarLockKeyError):
            locking.derive_northstar_seed_lock_key(noncanonical)


def test_advisory_key_is_stable_in_a_second_python_process() -> None:
    expected = str(locking.derive_northstar_seed_lock_key("northstar-clueso-demo"))
    program = (
        "from scripts.northstar_demo.locking import derive_northstar_seed_lock_key; "
        "print(derive_northstar_seed_lock_key('northstar-clueso-demo'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        check=True,
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    assert result.stdout.strip() == expected


async def _assert_disposable_0104(session: AsyncSession) -> None:
    database_name = str((await session.execute(text("SELECT current_database()"))).scalar_one())
    assert database_name.startswith(_DISPOSABLE_PREFIX)
    assert database_name not in _FORBIDDEN_DATABASES
    assert (
        await session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0104_connector_credentials_rls"
    assert (
        await session.execute(
            text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL")
        )
    ).scalar_one() is False


async def _backend_id(session: AsyncSession) -> int:
    return int((await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())


async def _fixture_counts(session: AsyncSession) -> tuple[int, ...]:
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


async def _classification(session: AsyncSession) -> NorthstarVerificationClassification:
    if session.in_transaction():
        await session.rollback()
    return (await verify_northstar_fixture_read_only(session, manifest=MANIFEST)).classification


async def _fresh_session(engine: AsyncEngine) -> AsyncSession:
    connection = await engine.connect()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    await _assert_disposable_0104(session)
    await session.rollback()
    session.info["northstar_test_connection"] = connection
    return session


async def _close_fresh_session(session: AsyncSession) -> None:
    connection = session.info.pop("northstar_test_connection")
    assert isinstance(connection, AsyncConnection)
    await session.close()
    await connection.close()


@requires_postgres
@pytest.mark.asyncio
async def test_gate_b2_real_two_connection_concurrency_contract(
    northstar_disposable_pg_engine: AsyncEngine,
) -> None:
    """Execute all committed-state scenarios in one disposable database.

    The order is intentional: lock timeout leaves ABSENT, rollback recovery
    creates the only fixture, complete/no-op then observes it, and the
    mismatched state is retained untouched until the entire database is
    removed by the Gate runner.
    """

    pg_engine = northstar_disposable_pg_engine
    test_url = str(pg_engine.url)
    target = validate_local_postgres_test_target(test_url)
    assert target.host_kind in {"localhost", "loopback"}
    assert target.database_name.startswith(_DISPOSABLE_PREFIX)
    assert target.database_name not in _FORBIDDEN_DATABASES

    async with AsyncSession(pg_engine, expire_on_commit=False) as initial:
        await _assert_disposable_0104(initial)
        assert await _classification(initial) is NorthstarVerificationClassification.ABSENT

    guards: list[SideEffectGuard] = []

    # Lock timeout: A owns the same transaction lock while B gets only the
    # sanitized busy result and never reaches fixture verification or writes.
    timeout_a = await _fresh_session(pg_engine)
    timeout_b = await _fresh_session(pg_engine)
    timeout_patch = pytest.MonkeyPatch()
    timeout_guard_context = install_northstar_side_effect_guards(timeout_patch)
    timeout_guard = timeout_guard_context.__enter__()
    held = asyncio.Event()
    release = asyncio.Event()

    async def hold_lock() -> None:
        held.set()
        await release.wait()

    timeout_task_a = asyncio.create_task(
        NorthstarDemoSeedService(
            timeout_a,
            serialize_execution=True,
            post_lock_barrier=hold_lock,
        ).seed()
    )
    await asyncio.wait_for(held.wait(), timeout=5)
    timeout_task_b = asyncio.create_task(
        NorthstarDemoSeedService(
            timeout_b,
            serialize_execution=True,
            lock_timeout_milliseconds=100,
        ).seed()
    )
    with pytest.raises(NorthstarConcurrentExecutionBusy):
        await asyncio.wait_for(timeout_task_b, timeout=5)
    with pytest.raises(asyncio.CancelledError):
        # The test explicitly closes A's connection instead of allowing a
        # fixture commit; transaction-scoped locks release on connection loss.
        timeout_task_a.cancel()
        await timeout_task_a
    await _close_fresh_session(timeout_a)
    await _close_fresh_session(timeout_b)
    assert timeout_guard.all_counts_zero
    guards.append(timeout_guard)
    timeout_guard_context.__exit__(None, None, None)
    timeout_patch.undo()
    async with AsyncSession(pg_engine, expire_on_commit=False) as after_timeout:
        await _assert_disposable_0104(after_timeout)
        assert await _classification(after_timeout) is NorthstarVerificationClassification.ABSENT
        assert await _fixture_counts(after_timeout) == (0,) * 10

    # A fails after holding the lock; B is blocked, then starts from ABSENT and
    # is the one real, successful commit.
    rollback_a = await _fresh_session(pg_engine)
    rollback_b = await _fresh_session(pg_engine)
    rollback_patch = pytest.MonkeyPatch()
    rollback_guard_context = install_northstar_side_effect_guards(rollback_patch)
    rollback_guard = rollback_guard_context.__enter__()
    rollback_held = asyncio.Event()
    rollback_release = asyncio.Event()
    rollback_b_locked = asyncio.Event()
    rollback_b_release = asyncio.Event()
    rollback_a_pid = 0
    rollback_b_pid = 0

    async def hold_rollback_a() -> None:
        nonlocal rollback_a_pid
        rollback_a_pid = await _backend_id(rollback_a)
        rollback_held.set()
        await rollback_release.wait()

    async def observe_rollback_b_lock() -> None:
        nonlocal rollback_b_pid
        rollback_b_pid = await _backend_id(rollback_b)
        rollback_b_locked.set()
        await rollback_b_release.wait()

    task_a = asyncio.create_task(
        NorthstarDemoSeedService(
            rollback_a,
            serialize_execution=True,
            post_lock_barrier=hold_rollback_a,
            failure_injector=lambda stage: stage is SeedStage.IMMEDIATELY_BEFORE_COMMIT,
        ).seed()
    )
    await asyncio.wait_for(rollback_held.wait(), timeout=5)
    task_b = asyncio.create_task(
        NorthstarDemoSeedService(
            rollback_b,
            serialize_execution=True,
            post_lock_barrier=observe_rollback_b_lock,
        ).seed()
    )
    await asyncio.sleep(0.15)
    assert not task_b.done()
    rollback_release.set()
    with pytest.raises(SeedInjectedFailure):
        await task_a
    await asyncio.wait_for(rollback_b_locked.wait(), timeout=5)
    assert rollback_a_pid != rollback_b_pid
    rollback_b_release.set()
    assert (await task_b).state == "complete"
    await _close_fresh_session(rollback_a)
    await _close_fresh_session(rollback_b)
    assert rollback_guard.all_counts_zero
    guards.append(rollback_guard)
    rollback_guard_context.__exit__(None, None, None)
    rollback_patch.undo()

    async with AsyncSession(pg_engine, expire_on_commit=False) as after_rollback:
        await _assert_disposable_0104(after_rollback)
        assert await _classification(after_rollback) is NorthstarVerificationClassification.COMPLETE_MATCH
        assert await _fixture_counts(after_rollback) == (1, 1, 1, 3, 1, 1, 1, 1, 1, 1)

    # The already-complete fixture is serialized by two new independent
    # sessions.  B cannot pass its lock barrier until A has committed, and B
    # emits no fixture DML after it acquires the lock and re-verifies COMPLETE.
    complete_a = await _fresh_session(pg_engine)
    complete_b = await _fresh_session(pg_engine)
    complete_patch = pytest.MonkeyPatch()
    complete_guard_context = install_northstar_side_effect_guards(complete_patch)
    complete_guard = complete_guard_context.__enter__()
    complete_a_held = asyncio.Event()
    complete_a_release = asyncio.Event()
    complete_b_locked = asyncio.Event()
    complete_b_release = asyncio.Event()
    b_dml: list[str] = []

    async def hold_complete_a() -> None:
        complete_a_held.set()
        await complete_a_release.wait()

    async def observe_complete_b_lock() -> None:
        connection = await complete_b.connection()
        sync_connection = connection.sync_connection
        assert sync_connection is not None
        sync_connection.info["northstar_complete_b"] = True
        complete_b_locked.set()
        await complete_b_release.wait()

    def capture_b_dml(
        connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        info = getattr(connection, "info", {})
        if info.get("northstar_complete_b") and statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE")
        ):
            b_dml.append(statement.split(maxsplit=1)[0].upper())

    event.listen(pg_engine.sync_engine, "before_cursor_execute", capture_b_dml)
    try:
        complete_task_a = asyncio.create_task(
            NorthstarDemoSeedService(
                complete_a,
                serialize_execution=True,
                post_lock_barrier=hold_complete_a,
            ).seed()
        )
        await asyncio.wait_for(complete_a_held.wait(), timeout=5)
        complete_task_b = asyncio.create_task(
            NorthstarDemoSeedService(
                complete_b,
                serialize_execution=True,
                post_lock_barrier=observe_complete_b_lock,
            ).seed()
        )
        await asyncio.sleep(0.15)
        assert not complete_task_b.done()
        complete_a_release.set()
        assert (await complete_task_a).state == "complete"
        await asyncio.wait_for(complete_b_locked.wait(), timeout=5)
        complete_b_release.set()
        assert (await complete_task_b).state == "complete"
    finally:
        event.remove(pg_engine.sync_engine, "before_cursor_execute", capture_b_dml)
        await _close_fresh_session(complete_a)
        await _close_fresh_session(complete_b)
    assert b_dml == []
    assert complete_guard.all_counts_zero
    guards.append(complete_guard)
    complete_guard_context.__exit__(None, None, None)
    complete_patch.undo()

    # Read-only verification remains independent of the advisory lock.  It
    # completes while another session holds the same future execute lock.
    reader_lock = await _fresh_session(pg_engine)
    reader = await _fresh_session(pg_engine)
    reader_patch = pytest.MonkeyPatch()
    reader_guard_context = install_northstar_side_effect_guards(reader_patch)
    reader_guard = reader_guard_context.__enter__()
    reader_held = asyncio.Event()
    reader_release = asyncio.Event()

    async def hold_reader_lock() -> None:
        reader_held.set()
        await reader_release.wait()

    reader_lock_task = asyncio.create_task(
        NorthstarDemoSeedService(
            reader_lock,
            serialize_execution=True,
            post_lock_barrier=hold_reader_lock,
        ).seed()
    )
    await asyncio.wait_for(reader_held.wait(), timeout=5)
    assert await asyncio.wait_for(_classification(reader), timeout=1) is NorthstarVerificationClassification.COMPLETE_MATCH
    reader_release.set()
    assert (await reader_lock_task).state == "complete"
    await _close_fresh_session(reader_lock)
    await _close_fresh_session(reader)
    assert reader_guard.all_counts_zero
    guards.append(reader_guard)
    reader_guard_context.__exit__(None, None, None)
    reader_patch.undo()

    # Commit a deliberate mismatch in the disposable target.  Neither
    # concurrent execute repairs, overwrites, or deletes it.
    async with AsyncSession(pg_engine, expire_on_commit=False) as mismatch_setup:
        await _assert_disposable_0104(mismatch_setup)
        await mismatch_setup.execute(
            text("UPDATE tenants SET status = 'provisioning' WHERE tenant_id = :tenant_id"),
            {"tenant_id": MANIFEST.tenant_id},
        )
        await mismatch_setup.commit()
    mismatch_a = await _fresh_session(pg_engine)
    mismatch_b = await _fresh_session(pg_engine)
    mismatch_patch = pytest.MonkeyPatch()
    mismatch_guard_context = install_northstar_side_effect_guards(mismatch_patch)
    mismatch_guard = mismatch_guard_context.__enter__()
    mismatch_a_held = asyncio.Event()
    mismatch_a_release = asyncio.Event()

    async def hold_mismatch_a() -> None:
        mismatch_a_held.set()
        await mismatch_a_release.wait()

    mismatch_task_a = asyncio.create_task(
        NorthstarDemoSeedService(
            mismatch_a,
            serialize_execution=True,
            post_lock_barrier=hold_mismatch_a,
        ).seed()
    )
    await asyncio.wait_for(mismatch_a_held.wait(), timeout=5)
    mismatch_task_b = asyncio.create_task(
        NorthstarDemoSeedService(mismatch_b, serialize_execution=True).seed()
    )
    await asyncio.sleep(0.15)
    assert not mismatch_task_b.done()
    mismatch_a_release.set()
    with pytest.raises(NorthstarSeedSafetyError):
        await mismatch_task_a
    with pytest.raises(NorthstarSeedSafetyError):
        await mismatch_task_b
    await _close_fresh_session(mismatch_a)
    await _close_fresh_session(mismatch_b)
    assert mismatch_guard.all_counts_zero
    guards.append(mismatch_guard)
    mismatch_guard_context.__exit__(None, None, None)
    mismatch_patch.undo()
    async with AsyncSession(pg_engine, expire_on_commit=False) as mismatch_check:
        await _assert_disposable_0104(mismatch_check)
        assert await _classification(mismatch_check) is NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH
        assert (
            await mismatch_check.execute(
                text("SELECT status FROM tenants WHERE tenant_id = :tenant_id"),
                {"tenant_id": MANIFEST.tenant_id},
            )
        ).scalar_one() == "provisioning"

    # Different canonical tenants use different xact keys and never block one
    # another.  This is direct PostgreSQL lock coverage, not a second fixture.
    isolation_a = await _fresh_session(pg_engine)
    isolation_b = await _fresh_session(pg_engine)
    tx_a = await isolation_a.begin()
    tx_b = await isolation_b.begin()
    try:
        await locking.acquire_northstar_seed_transaction_lock(
            isolation_a, tenant_id="northstar-clueso-demo"
        )
        await asyncio.wait_for(
            locking.acquire_northstar_seed_transaction_lock(
                isolation_b, tenant_id="northstar-clueso-demo-2"
            ),
            timeout=1,
        )
    finally:
        await tx_a.rollback()
        await tx_b.rollback()
        await _close_fresh_session(isolation_a)
        await _close_fresh_session(isolation_b)
    assert guards and all(guard.all_counts_zero for guard in guards)


def test_post_lock_barrier_is_constructor_only_and_cli_modes_do_not_lock() -> None:
    backend_root = Path(__file__).parent.parent
    source = (backend_root / "scripts" / "northstar_demo" / "__main__.py").read_text()
    assert "post_lock_barrier" not in source
    assert "lock_timeout" not in source
    assert "serialize_execution=True" in (
        backend_root / "scripts" / "northstar_demo" / "commit_reconciliation.py"
    ).read_text()
    barrier_references = {
        path.relative_to(backend_root).as_posix()
        for path in backend_root.rglob("*.py")
        if "post_lock_barrier" in path.read_text()
    }
    assert barrier_references == {
        "scripts/northstar_demo/seed.py",
        "tests/test_northstar_seed_concurrency.py",
    }
