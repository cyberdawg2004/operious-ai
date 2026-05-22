"""Phase 3-B QA chronology projection tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import (
    CAPABILITY_GOVERNED_ACTS,
    OperationalAct,
)
from app.qa.persistence import InMemoryQAPersistence, QAScoreRecord
from app.runtime.qa_event_projection import (
    QAEventProjectionError,
    QAOperationalEventProjector,
    project_qa_score_record,
)


_NOW = datetime(2026, 5, 22, 11, tzinfo=timezone.utc)
_SCORE_ID = "00000000-0000-0000-0000-000000003101"
_INSPECTION_ID = "00000000-0000-0000-0000-000000003102"
_EXECUTION_ID = "00000000-0000-0000-0000-000000003103"


def _score(*, tenant_id: str = "tenant-acme") -> QAScoreRecord:
    return QAScoreRecord(
        score_id=_SCORE_ID,
        inspection_id=_INSPECTION_ID,
        execution_id=_EXECUTION_ID,
        tenant_id=tenant_id,
        tenant_authority_source="header",
        diagnostic_accuracy=0.9,
        policy_compliance=0.8,
        timeline_integrity=1.0,
        resolution_quality=0.7,
        overall_score=0.85,
        supervisor_decision_kind="accept",
        finding_count=1,
        evaluation_count=4,
        escalation_count=0,
        scored_at=_NOW.isoformat(),
        metadata={"fixture": "phase-3b"},
    )


def test_qa_score_projects_to_canonical_event() -> None:
    record = _score()

    event = project_qa_score_record(record=record)

    assert event.event_id == record.score_id
    assert event.operational_act is OperationalAct.QA_SCORE
    assert event.substrate is OperationalSubstrate.QA
    assert event.causality.root_event_id == event.event_id
    assert event.causality.parent_event_id is None
    assert event.causality.depth == 0
    assert event.chronology.occurred_at == _NOW
    assert event.chronology.sequence == 0
    assert event.tenant_id == "tenant-acme"
    assert event.tenant_authority_source == "header"
    assert event.governance_decision is None
    assert event.metadata["projection_source"] == "qa_score"
    assert event.metadata["source_score_id"] == record.score_id
    assert event.metadata["source_qa_score_record"] == record.to_dict()


@pytest.mark.asyncio
async def test_projector_projects_score_idempotently() -> None:
    qa_repo = InMemoryQAPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _score()
    await qa_repo.record_score(record, expected_tenant_id="tenant-acme")
    projector = QAOperationalEventProjector(
        qa_persistence=qa_repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_score(
        record.score_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_inspection_score(
        record.inspection_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.QA,
            tenant_id="tenant-acme",
        )
    )

    assert second == first
    assert page.total == 1
    assert first.source_record == record


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    qa_repo = InMemoryQAPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _score(tenant_id="tenant-acme")
    await qa_repo.record_score(record, expected_tenant_id="tenant-acme")
    projector = QAOperationalEventProjector(
        qa_persistence=qa_repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(QAEventProjectionError):
        await projector.project_score(
            record.score_id,
            expected_tenant_id="tenant-other",
        )


def test_qa_score_act_is_projection_only() -> None:
    assert OperationalAct.QA_SCORE not in CAPABILITY_GOVERNED_ACTS


def test_qa_source_substrate_does_not_import_event_fabric() -> None:
    root = Path("apps/backend/app/qa")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from app.events" in text or "import app.events" in text:
            offenders.append(str(path))

    assert not offenders
