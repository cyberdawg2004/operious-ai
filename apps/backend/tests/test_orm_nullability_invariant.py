"""ORM <-> migration nullability invariant (#65).

Every ORM-mapped column's nullability must match the migrated database schema.
Drift (ORM says nullable, DB says NOT NULL, or vice versa) is a type-safety
hazard: code can construct a row the ORM accepts but the DB rejects. This is the
automated forcing function in place of manual review.

Runs against the migrated test database (requires Postgres); skipped when
TEST_DATABASE_URL is not configured.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

# Import every ORM model module so it registers on ``Base.metadata`` (mirrors
# migrations/env.py). Missing one here would silently drop it from the check.
from app.db.base import Base
import app.db.models  # noqa: F401
import app.governance.db.models  # noqa: F401
import app.session.db.models  # noqa: F401
import app.coordination.db.models  # noqa: F401
import app.arbitration.db.models  # noqa: F401
import app.supervisor.db.models  # noqa: F401
import app.boundary.db.models  # noqa: F401
import app.boundary.voice.db.models  # noqa: F401
import app.execution.db.models  # noqa: F401
import app.events.db.models  # noqa: F401
import app.tenant.db.models  # noqa: F401
import app.knowledge.db.models  # noqa: F401
import app.qa.db.models  # noqa: F401
import app.escalation.db.models  # noqa: F401
import app.approvals.db.models  # noqa: F401
import app.sop_intelligence.db.models  # noqa: F401
import app.trainer.db.models  # noqa: F401
import app.cognition.db.models  # noqa: F401
import app.data_protection.db.models  # noqa: F401
import app.observability.db.models  # noqa: F401
import app.runtime.db.models  # noqa: F401
import app.resolution.db.models  # noqa: F401
from tests.conftest import TEST_DATABASE_URL_ENV, requires_postgres

pytestmark = requires_postgres

# Documented, reviewable exceptions (table, column) where ORM and DB nullability
# legitimately differ. Empty by default: every column must match.
_NULLABILITY_EXCEPTIONS: frozenset[tuple[str, str]] = frozenset()


@pytest_asyncio.fixture
async def db_conn() -> AsyncIterator[asyncpg.Connection]:
    dsn = os.environ[TEST_DATABASE_URL_ENV].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def test_orm_nullability_matches_migrated_schema(
    db_conn: asyncpg.Connection,
) -> None:
    rows = await db_conn.fetch(
        """
        SELECT table_name, column_name, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        """
    )
    db: dict[str, dict[str, bool]] = {}
    for row in rows:
        db.setdefault(row["table_name"], {})[row["column_name"]] = (
            row["is_nullable"] == "YES"
        )

    mismatches: list[str] = []
    for table in Base.metadata.sorted_tables:
        db_table = db.get(table.name)
        if db_table is None:
            continue
        for column in table.columns:
            if column.name not in db_table:
                continue
            if (table.name, column.name) in _NULLABILITY_EXCEPTIONS:
                continue
            orm_nullable = bool(column.nullable)
            db_nullable = db_table[column.name]
            if orm_nullable != db_nullable:
                mismatches.append(
                    f"{table.name}.{column.name}: "
                    f"orm_nullable={orm_nullable} db_nullable={db_nullable}"
                )

    assert not mismatches, (
        "ORM/migration nullability drift detected (align the ORM "
        "mapped_column with the migration, or add a documented exception):\n  "
        + "\n  ".join(sorted(mismatches))
    )
