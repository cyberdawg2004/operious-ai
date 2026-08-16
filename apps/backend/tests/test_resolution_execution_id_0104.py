"""Regression proof for nullable proposal execution lineage at schema 0104."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.resolution.db.models import ResolutionProposalRow
from app.resolution.persistence import PostgresResolutionProposalPersistence
from scripts.northstar_demo.manifest import MANIFEST
from scripts.northstar_demo.seed import NorthstarDemoSeedService

_BACKEND_ROOT = Path(__file__).resolve().parents[1]


async def _assert_0104(session: AsyncSession) -> None:
    assert (
        await session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0104_connector_credentials_rls"
    assert (
        await session.execute(
            text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL")
        )
    ).scalar_one() is False


async def test_resolution_proposal_execution_id_is_nullable_and_serializes_at_0104(
    pg_engine: AsyncEngine,
) -> None:
    """Use the real mapper with a rollback-only fixture row whose lineage is null."""

    connection = await pg_engine.connect()
    outer = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        await _assert_0104(session)
        column = (
            await session.execute(
                text(
                    """
                    SELECT is_nullable, data_type, udt_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'resolution_proposals'
                      AND column_name = 'execution_id'
                    """
                )
            )
        ).one()
        assert column == ("YES", "uuid", "uuid")
        assert ResolutionProposalRow.__table__.c.execution_id.nullable is True
        assert "None" in str(ResolutionProposalRow.__annotations__["execution_id"])

        await session.rollback()
        created = await NorthstarDemoSeedService(session).seed()
        assert created.state == "complete"
        proposal = await PostgresResolutionProposalPersistence(session).get_resolution_proposal(
            str(MANIFEST.proposal_id),
            expected_tenant_id=MANIFEST.tenant_id,
        )
        assert proposal is not None
        assert proposal.execution_id is None
        assert proposal.to_dict()["execution_id"] is None

        constraint = (
            await session.execute(
                text(
                    """
                    SELECT confdeltype
                    FROM pg_constraint
                    WHERE conname = 'fk_resolution_proposals_execution_id'
                    """
                )
            )
        ).scalar_one().decode()
        assert constraint == "n"
        mapper_source = (
            _BACKEND_ROOT / "app/resolution/persistence/postgres.py"
        ).read_text().casefold()
        assert "northstar" not in mapper_source
    finally:
        await session.close()
        await outer.rollback()
        await connection.close()
