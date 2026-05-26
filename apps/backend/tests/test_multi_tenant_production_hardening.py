"""Phase 6-D multi-tenant production hardening coverage."""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import pytest

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryIngressId,
    derive_event_id as derive_boundary_event_id,
)
from app.boundary.persistence import (
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
)
from app.boundary.adapters import EmailWebhookAdapter
from app.events import (
    EventCausality,
    EventChronology,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct
from app.runtime.boundary_event_projection import project_boundary_ingress_record
from app.runtime.tenant_production_hardening import (
    TenantProductionHardeningRuntime,
    sign_audit_export_payload,
)
from app.services.ticket_ingress_service import TicketIngressService
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.identity import derive_channel_configuration_id
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

_NOW = datetime(2026, 5, 23, tzinfo=timezone.utc)
_RUNTIME_ID = uuid.UUID("6117d3ff-82d1-5185-9157-8cf9f56ef743")
_MASTER_KEY = "phase-6-d-master-key-32-bytes-minimum"
_SIGNING_KEY = "phase-6-d-audit-signing-key"


class _FakeSession:
    async def commit(self) -> None:
        return None


def test_migration_enables_rls_for_all_current_substrate_tables() -> None:
    migration = _load_migration()
    direct = set(migration.TENANT_RLS_DIRECT_TABLES)
    inherited = {item[0] for item in migration.TENANT_RLS_PARENT_TABLES}
    covered = direct | inherited

    expected = {
        "tenants",
        "governance_decisions",
        "governance_traces",
        "governance_enforcement_actions",
        "operational_sessions",
        "session_events",
        "session_correlations",
        "coordination_envelopes",
        "arbitration_evaluations",
        "supervisor_inspections",
        "supervisor_findings",
        "supervisor_evaluations",
        "supervisor_escalations",
        "boundary_ingress",
        "boundary_egress",
        "execution_records",
        "execution_attempts",
        "execution_outbox",
        "operational_events",
        "tenant_channel_configurations",
        "tenant_knowledge_documents",
        "tenant_knowledge_document_versions",
        "tenant_governance_policies",
        "tenant_topology_configurations",
        "tenant_knowledge_chunks",
        "tenant_knowledge_vectors",
        "qa_score_records",
        "escalation_records",
        "approval_records",
        "cognition_llm_usage_records",
        "operational_slo_definitions",
        "operational_trace_spans",
        "tenant_execution_governance_configurations",
        "tenant_execution_circuit_breakers",
    }

    assert expected <= covered
    source = _migration_path().read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows" in source


def test_partitioning_strategy_is_documented_in_migration() -> None:
    migration = _load_migration()
    assert "LIST (tenant_id)" in migration.TENANT_PARTITION_STRATEGY_COMMENT
    assert "DEFAULT partition" in migration.TENANT_PARTITION_STRATEGY_COMMENT


@pytest.mark.asyncio
async def test_credential_rotation_preserves_previous_secret_during_grace_window() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=_MASTER_KEY,
        ),
    )
    config = await tenant_runtime.configure_channel(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"api_key": "old-secret"},
        webhook_secret="old-webhook-secret",
        status=TenantChannelStatus.ACTIVE,
    )
    rotated = await tenant_runtime.rotate_channel_credentials(
        tenant_id="tenant-acme",
        config_id=config.config_id,
        credentials={"api_key": "new-secret"},
        webhook_secret="new-webhook-secret",
        grace_period_minutes=30,
    )

    assert rotated.config_id == derive_channel_configuration_id(
        tenant_id="tenant-acme",
        channel_type=TenantChannelType.EMAIL,
    )
    assert rotated.previous_webhook_secret == "old-webhook-secret"
    assert rotated.previous_credentials_enc is not None
    assert b"old-secret" not in rotated.previous_credentials_enc
    assert b"new-secret" not in rotated.credentials_enc

    service = TicketIngressService(
        persistence=boundary_store,
        session=_FakeSession(),  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
    )
    body = {
        "message_id": "email-message-6d",
        "to": "support@example.com",
        "text": "old signatures still land during grace",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=_signed_headers(secret="old-webhook-secret", raw_body=_raw(body)),
        raw_body=_raw(body),
        content_type="application/json",
    )

    page = await boundary_store.list_ingress(
        query=BoundaryIngressQuery(),
        expected_tenant_id="tenant-acme",
    )
    assert page.total == 1
    assert result.ingress_id == str(page.ingress[0].ingress_id)


@pytest.mark.asyncio
async def test_signed_audit_export_is_tenant_scoped_and_verifiable() -> None:
    event_store = InMemoryOperationalEventPersistence()
    event_runtime = OperationalEventRuntime(persistence=event_store)
    await event_runtime.append_event(_event(tenant_id="tenant-acme", sequence=0))
    await event_runtime.append_event(_event(tenant_id="tenant-other", sequence=1))
    runtime = TenantProductionHardeningRuntime(
        event_persistence=event_store,
        boundary_persistence=InMemoryBoundaryPersistence(),
        audit_export_signing_key=_SIGNING_KEY,
    )

    export = await runtime.create_audit_export(
        tenant_id="tenant-acme",
        from_timestamp=datetime(2026, 5, 22, tzinfo=timezone.utc),
        to_timestamp=datetime(2026, 5, 24, tzinfo=timezone.utc),
        limit=100,
    )

    assert export.tenant_id == "tenant-acme"
    assert export.event_count == 1
    assert export.payload["events"][0]["tenant_id"] == "tenant-acme"
    assert "tenant-other" not in json.dumps(export.payload, sort_keys=True)
    assert export.signature == sign_audit_export_payload(
        payload=export.payload,
        signing_key=_SIGNING_KEY,
    )


@pytest.mark.asyncio
async def test_incident_replay_is_tenant_scoped_and_read_only() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    event_store = InMemoryOperationalEventPersistence()
    event_runtime = OperationalEventRuntime(persistence=event_store)
    tenant_record = _ingress_record(tenant_id="tenant-acme", ticket_id="ticket-6d")
    other_record = _ingress_record(tenant_id="tenant-other", ticket_id="ticket-6d")
    await boundary_store.save_ingress(tenant_record)
    await boundary_store.save_ingress(other_record)
    await event_runtime.append_event(project_boundary_ingress_record(tenant_record))
    runtime = TenantProductionHardeningRuntime(
        event_persistence=event_store,
        boundary_persistence=boundary_store,
        audit_export_signing_key=_SIGNING_KEY,
    )

    replay = await runtime.replay_ticket(
        tenant_id="tenant-acme",
        ticket_id="ticket-6d",
    )

    assert replay.status == "complete"
    assert replay.boundary_ingress_count == 1
    assert replay.traces[0].ingress_id == str(tenant_record.ingress_id)
    assert replay.traces[0].events[0]["tenant_id"] == "tenant-acme"
    assert "tenant-other" not in json.dumps(
        [dict(trace.metadata) for trace in replay.traces],
        sort_keys=True,
    )


def test_tenant_router_stays_service_layered_for_hardening_surfaces() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "v1"
        / "routers"
        / "tenant.py"
    ).read_text(encoding="utf-8")
    assert "TenantProductionHardeningRuntime" not in source
    assert "PostgresOperationalEventPersistence" not in source
    assert "PostgresBoundaryPersistence" not in source
    assert "Depends(require_tenant_scope)" in source


def test_transport_workers_do_not_own_production_hardening() -> None:
    workers_dir = Path(__file__).resolve().parents[1] / "app" / "workers"
    worker_text = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(workers_dir.glob("*.py"))
    )
    assert "TenantProductionHardeningRuntime" not in worker_text
    assert "create_audit_export" not in worker_text
    assert "replay_ticket" not in worker_text


def _event(*, tenant_id: str, sequence: int) -> OperationalEvent:
    event_id = derive_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=_RUNTIME_ID,
        sequence=sequence,
        tenant_id=tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.BOUNDARY_INGEST,
        substrate=OperationalSubstrate.BOUNDARY,
        causality=EventCausality(
            root_event_id=event_id,
            parent_event_id=None,
            depth=0,
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME_ID,
            sequence=sequence,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        metadata={"ticket_id": f"ticket-{tenant_id}"},
    )


def _ingress_record(*, tenant_id: str, ticket_id: str) -> BoundaryIngressRecord:
    event_id = derive_boundary_event_id(
        source_type=BoundarySourceType.EMAIL,
        external_message_id=ticket_id,
        tenant_id=tenant_id,
    )
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(uuid.uuid5(uuid.NAMESPACE_URL, tenant_id)),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=_RUNTIME_ID,
        sequence=0,
        source_type=BoundarySourceType.EMAIL,
        source_id=f"{tenant_id}:support@example.com",
        tenant_id=tenant_id,
        adapter_name=EmailWebhookAdapter.DEFAULT_NAME,
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:{ticket_id}"),
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=ticket_id,
        external_conversation_id=ticket_id,
        external_emitted_at=None,
        received_at=_NOW,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=1.0,
        correlation_id=ticket_id,
        request_id=ticket_id,
        canonical_payload={"ticket_id": ticket_id, "message_id": ticket_id},
        error=None,
        metadata={"ticket.external_id": ticket_id},
    )


def _signed_headers(*, secret: str, raw_body: bytes) -> dict[str, str]:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return {"X-Operious-Signature": f"sha256={digest}"}


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "phase_6d_migration",
        _migration_path(),
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0025_multi_tenant_production_hardening.py"
    )
