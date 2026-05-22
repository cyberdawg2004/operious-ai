"""Postgres escalation persistence tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.escalation import (
    EscalationPersistenceError,
    EscalationStatus,
    derive_escalation_id,
)
from app.escalation.persistence import (
    EscalationQuery,
    EscalationRecord,
    PostgresEscalationPersistence,
)
from app.governance.persistence import (
    GovernanceDecisionRecord,
    PostgresGovernanceRepository,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import PostgresSessionPersistence, SessionRecord
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)
_SESSION_ID = "00000000-0000-0000-0000-000000003d01"
_DENY_ID = "00000000-0000-0000-0000-000000003d02"


def _session(*, tenant_id: str = "tenant-acme") -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-pg",
        tenant_id=tenant_id,
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _decision(*, tenant_id: str = "tenant-acme") -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=_DENY_ID,
        decision="deny",
        stage="pre_execution",
        policy_chain_id="test.chain",
        reason="deny",
        decided_at=_NOW.isoformat(),
        tenant_id=tenant_id,
        metadata={"session_id": _SESSION_ID},
    )


def _record(*, tenant_id: str = "tenant-acme") -> EscalationRecord:
    return EscalationRecord(
        escalation_id=str(
            derive_escalation_id(
                tenant_id=tenant_id,
                session_id=_SESSION_ID,
                governance_decision_id=_DENY_ID,
            )
        ),
        session_id=_SESSION_ID,
        tenant_id=tenant_id,
        reason="deny",
        governance_decision_id=_DENY_ID,
        status=EscalationStatus.PENDING.value,
        created_at=_NOW.isoformat(),
        metadata={"fixture": "postgres"},
    )


async def _seed_lineage(pg_session: AsyncSession) -> None:
    await PostgresSessionPersistence(pg_session).save_session(_session())
    await PostgresGovernanceRepository(pg_session).record_decision(
        _decision()
    )


@pytest.mark.asyncio
async def test_postgres_escalation_persistence_enforces_tenant_scope(
    pg_session: AsyncSession,
) -> None:
    await _seed_lineage(pg_session)
    repo = PostgresEscalationPersistence(pg_session)
    record = _record()

    await repo.create_escalation(record, expected_tenant_id="tenant-acme")

    assert await repo.get_escalation(
        record.escalation_id,
        expected_tenant_id="tenant-acme",
    ) == record
    assert await repo.get_escalation(
        record.escalation_id,
        expected_tenant_id="tenant-other",
    ) is None
    page = await repo.list_escalations(
        EscalationQuery(status=EscalationStatus.PENDING.value),
        expected_tenant_id="tenant-acme",
    )
    assert page.total == 1
    assert page.items == (record,)
    other_page = await repo.list_escalations(
        EscalationQuery(status=EscalationStatus.PENDING.value),
        expected_tenant_id="tenant-other",
    )
    assert other_page.total == 0


@pytest.mark.asyncio
async def test_postgres_escalation_write_rejects_expected_tenant_mismatch(
    pg_session: AsyncSession,
) -> None:
    await _seed_lineage(pg_session)
    repo = PostgresEscalationPersistence(pg_session)

    with pytest.raises(EscalationPersistenceError, match="expected_tenant_id"):
        await repo.create_escalation(
            _record(),
            expected_tenant_id="tenant-other",
        )
