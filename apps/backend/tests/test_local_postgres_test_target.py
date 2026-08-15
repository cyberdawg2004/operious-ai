"""Fail-closed test target validation for PostgreSQL integration fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.test_target import (
    LocalTestDatabaseTargetError,
    create_checked_test_resource,
    validate_local_postgres_test_target,
)
from tests.conftest import requires_postgres


@pytest.mark.parametrize(
    ("dsn", "host_kind", "database_name"),
    [
        ("postgresql+asyncpg://test:test@localhost:5433/operious_test", "localhost", "operious_test"),
        ("postgresql://test:test@127.0.0.1:5433/test_operious", "loopback", "test_operious"),
        ("postgresql+psycopg2://test:test@[::1]:5433/OPERIOUS_TEST", "loopback", "operious_test"),
        ("postgresql+asyncpg://test:test@postgres:5432/operious_test", "local-test-container", "operious_test"),
        ("postgresql+asyncpg://test:test@localhost./operious%5Ftest", "localhost", "operious_test"),
        ("postgresql+asyncpg://test:test@/operious_test?host=%2Fvar%2Frun%2Fpostgresql", "unix_socket", "operious_test"),
    ],
)
def test_accepts_only_explicit_local_postgres_test_targets(
    dsn: str, host_kind: str, database_name: str
) -> None:
    target = validate_local_postgres_test_target(dsn)
    assert target.host_kind == host_kind
    assert target.database_name == database_name


@pytest.mark.parametrize(
    "dsn",
    [
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://test:test@db.example.com/operious_test",
        "postgresql+asyncpg://test:test@neon.example/operious_test",
        "postgresql+asyncpg://test:test@host.rds.amazonaws.com/operious_test",
        "postgresql+asyncpg://test:test@10.0.0.5/operious_test",
        "postgresql+asyncpg://test:test@localhost/operious",
        "postgresql+asyncpg://test:test@localhost/",
        "postgresql+asyncpg://test:test@/operious_test",
        "not a URL",
    ],
)
def test_rejects_nonlocal_or_non_test_targets_without_leaking_dsn(dsn: str) -> None:
    with pytest.raises(LocalTestDatabaseTargetError) as excinfo:
        validate_local_postgres_test_target(dsn)
    assert dsn not in str(excinfo.value)
    assert "test:test" not in str(excinfo.value)


def test_rejection_happens_before_a_connection_resource_is_created() -> None:
    called = False

    def _factory(_: str) -> object:
        nonlocal called
        called = True
        return object()

    with pytest.raises(LocalTestDatabaseTargetError):
        create_checked_test_resource(
            "postgresql+asyncpg://test:test@db.example.com/operious_test",
            _factory,
        )
    assert called is False


def test_accepted_target_invokes_factory_only_after_validation() -> None:
    token = object()
    assert create_checked_test_resource(
        "postgresql+asyncpg://test:test@localhost:5433/operious_test",
        lambda _: token,
    ) is token


@requires_postgres
@pytest.mark.asyncio
async def test_accepted_local_target_connects_to_postgres(
    pg_engine: AsyncEngine,
) -> None:
    async with pg_engine.connect() as connection:
        assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
