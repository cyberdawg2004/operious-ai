from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest

from app.api.v1.schemas.session import SessionTimelineResponse
from app.execution.envelope import (
    CURRENT_SCHEMA_VERSION,
    ExecutionResultEnvelope,
    PRE_VERSIONED_SCHEMA_VERSION,
)
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.resolution_runtime import (
    ResolutionProposalRequest,
    ResolutionRuntime,
)
from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.session.enums import SessionContinuityMode, SessionEventKind
from app.session.identity import SessionId
from app.session.models.timeline import SessionTimeline
from app.session.timeline.builder import build_event
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)


def test_envelope_roundtrip() -> None:
    envelope = ExecutionResultEnvelope(
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
        diagnostic_summary="Battery diagnostic completed.",
        governance_decision_id="gov-1",
        governance_decision="ALLOW",
        resolution_proposal_id="proposal-1",
        resolution_draft_id="draft-1",
        error_code="none",
        error_message="none",
        metadata={"provider": "deterministic"},
    )

    restored = ExecutionResultEnvelope.from_dict(envelope.to_dict())

    assert restored == envelope
    assert restored.metadata == {"provider": "deterministic"}


def test_schema_version_in_dict() -> None:
    envelope = ExecutionResultEnvelope()

    assert envelope.to_dict()["_schema_version"] == CURRENT_SCHEMA_VERSION


def test_from_dict_tolerates_missing_version() -> None:
    envelope = ExecutionResultEnvelope.from_dict(
        {"diagnostic_category": "charging_issue"}
    )

    assert envelope.schema_version == PRE_VERSIONED_SCHEMA_VERSION
    assert envelope.diagnostic_category == "charging_issue"


def test_from_dict_unknown_keys_go_to_metadata() -> None:
    envelope = ExecutionResultEnvelope.from_dict(
        {"future_field": "x", "_schema_version": "2"}
    )

    assert envelope.schema_version == "2"
    assert envelope.metadata["future_field"] == "x"


def test_timeline_payload_has_schema_version() -> None:
    now = datetime.now(tz=timezone.utc)
    event = build_event(
        session_id=SessionId(uuid.uuid4()),
        sequence=0,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=now,
        recorded_at=now,
        payload={"event_type": "diagnostic_analysis_completed"},
    )

    assert event.payload["_schema_version"] == CURRENT_SCHEMA_VERSION


def test_timeline_api_projects_diagnostic_completed() -> None:
    now = datetime.now(tz=timezone.utc)
    session_id = SessionId(uuid.uuid4())
    event = build_event(
        session_id=session_id,
        sequence=0,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=now,
        recorded_at=now,
        payload={
            "event_type": "diagnostic_analysis_completed",
            "tenant_id": "tenant-a",
            "timestamp": now.isoformat(),
            "payload": {
                "category": "charging_issue",
                "confidence": 0.91,
                "summary": "Charging diagnostic completed.",
                "governance_decision_id": "gov-1",
            },
        },
        annotation="diagnostic_analysis_completed",
    )

    response = SessionTimelineResponse.from_timeline(
        SessionTimeline(session_id=session_id, events=(event,), head_sequence=0),
        fallback_tenant_id="tenant-a",
    )

    payload = response.events[0].payload
    assert payload["schema_version"] == CURRENT_SCHEMA_VERSION
    assert payload["category"] == "charging_issue"
    assert payload["confidence"] == 0.91
    assert payload["summary"] == "Charging diagnostic completed."
    assert payload["governance_decision_id"] == "gov-1"


async def _resolution_taxonomy_repository(
    *, tenant_id: str, category_ids: frozenset[str], version: int = 1
) -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    parameters: dict[str, object] = {
        "categories": [
            {
                "id": category_id,
                "label": category_id.replace("_", " ").title(),
                "description": f"Issues classified as {category_id}.",
                "recommended_actions": [
                    {
                        "type": "collect_context",
                        "label": "Gather additional details from the customer "
                        "before proceeding",
                        "requires_execution": False,
                    }
                ],
            }
            for category_id in sorted(category_ids)
        ],
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": "policy-admin",
            "effective_from": now.isoformat(),
            "source_approval_id": "approval-resolution-taxonomy",
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by="policy-admin",
        effective_from=now,
        created_at=now,
        source_approval_id="approval-resolution-taxonomy",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)
    return repository


@pytest.mark.asyncio
async def test_resolution_runtime_reads_via_envelope() -> None:
    stored_result = ExecutionResultEnvelope(
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
        diagnostic_summary="Charging issue found.",
    ).to_dict()

    envelope = ExecutionResultEnvelope.from_dict(stored_result)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=await _resolution_taxonomy_repository(
            tenant_id="tenant-envelope", category_ids=frozenset({"charging_issue"})
        ),
    ).create_proposal(
        ResolutionProposalRequest(
            tenant_id="tenant-envelope",
            session_id=str(uuid.uuid4()),
            execution_id=str(uuid.uuid4()),
            dispatch_id=str(uuid.uuid4()),
            diagnostic_event_id=str(uuid.uuid4()),
            diagnostic_summary=envelope.diagnostic_summary or "",
            diagnostic_category=envelope.diagnostic_category or "unknown",
            diagnostic_confidence=envelope.diagnostic_confidence or 0.0,
            original_content="My PowerCore stopped charging.",
        )
    )

    assert record.resolution_category == "charging_issue"
