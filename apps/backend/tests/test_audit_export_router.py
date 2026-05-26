"""PR_T12 signed audit export endpoint coverage."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from app.api.v1.schemas.audit_export import AuditExportResponse
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.core.config import get_settings
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_audit_export_service
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
from app.main import create_app
from app.runtime.tenant_production_hardening import (
    AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY,
    TenantProductionHardeningRuntime,
    sign_audit_export_payload,
    signed_audit_export_payload,
)
from app.services.audit_export_service import AuditExportService

_NOW = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
_RUNTIME_ID = uuid.UUID("7e90b4de-14fb-53f7-9a8a-bcb9f4ec1412")
_SIGNING_KEY = "phase-two-audit-export-signing-material"
_TENANT_ID = "tenant-acme"
_OTHER_TENANT_ID = "tenant-other"


@pytest_asyncio.fixture
async def audit_export_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, InMemoryOperationalEventPersistence]]:
    monkeypatch.setenv(_export_signing_env(), _SIGNING_KEY)
    get_settings.cache_clear()
    app = create_app()
    event_store = InMemoryOperationalEventPersistence()
    service = AuditExportService(
        runtime=TenantProductionHardeningRuntime(
            event_persistence=event_store,
            boundary_persistence=InMemoryBoundaryPersistence(),
            audit_export_signing_key=_SIGNING_KEY,
        )
    )
    app.dependency_overrides[get_audit_export_service] = _service_override(
        service
    )
    app.dependency_overrides[require_tenant_scope] = _tenant_scope_override

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client, event_store

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_audit_export_returns_signed_response(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)

    response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )

    assert response.status_code == 200
    body = response.json()
    assert AuditExportResponse.model_validate(body)
    assert body["tenant_id"] == _TENANT_ID
    assert body["event_count"] == 1
    assert body["total_available"] == 1
    assert body["truncated"] is False
    assert body["events"][0]["tenant_id"] == _TENANT_ID
    assert body["signature"]["algorithm"] == "HMAC-SHA256"
    assert body["signature"]["key_hint"] == _key_hint()


@pytest.mark.asyncio
async def test_audit_export_hmac_is_verifiable(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)

    response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )

    body = response.json()
    expected = sign_audit_export_payload(
        payload=signed_audit_export_payload(body),
        signing_key=_SIGNING_KEY,
    )
    assert body["signature"]["value"] == expected


@pytest.mark.asyncio
async def test_audit_export_rls_blocks_cross_tenant(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)
    await _append_event(event_store, tenant_id=_OTHER_TENANT_ID, sequence=1)

    response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 1
    assert body["events"][0]["tenant_id"] == _TENANT_ID
    assert _OTHER_TENANT_ID not in json.dumps(body, sort_keys=True)


@pytest.mark.asyncio
async def test_audit_verify_accepts_valid_export(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)
    export_response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )

    verify_response = await client.post(
        "/api/v1/audit/verify",
        json={"export": export_response.json()},
    )

    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["valid"] is True
    assert body["tenant_id"] == _TENANT_ID
    assert body["event_count"] == 1


@pytest.mark.asyncio
async def test_audit_verify_rejects_tampered_export(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)
    export_response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )
    export = export_response.json()
    export["events"][0]["metadata"]["ticket_id"] = "ticket-tampered"

    verify_response = await client.post(
        "/api/v1/audit/verify",
        json={"export": export},
    )

    assert verify_response.status_code == 200
    body = verify_response.json()
    assert body["valid"] is False
    assert body["tenant_id"] == _TENANT_ID
    assert body["event_count"] == 1


@pytest.mark.asyncio
async def test_audit_export_503_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_export_signing_env(), raising=False)
    get_settings.cache_clear()
    app = create_app()
    service = AuditExportService(
        runtime=TenantProductionHardeningRuntime(
            event_persistence=InMemoryOperationalEventPersistence(),
            boundary_persistence=InMemoryBoundaryPersistence(),
            audit_export_signing_key=AUDIT_EXPORT_UNCONFIGURED_SIGNING_KEY,
        )
    )
    app.dependency_overrides[get_audit_export_service] = _service_override(
        service
    )
    app.dependency_overrides[require_tenant_scope] = _tenant_scope_override

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/audit/export",
            headers=_headers(),
            params=_window_params(),
        )

    assert response.status_code == 503
    assert response.json()["title"] == "audit_export_not_configured"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_key_hint_does_not_expose_secret(
    audit_export_client: tuple[
        httpx.AsyncClient,
        InMemoryOperationalEventPersistence,
    ],
) -> None:
    client, event_store = audit_export_client
    await _append_event(event_store, tenant_id=_TENANT_ID, sequence=0)

    response = await client.get(
        "/api/v1/audit/export",
        headers=_headers(),
        params=_window_params(),
    )

    body = response.json()
    key_hint = body["signature"]["key_hint"]
    assert key_hint == _key_hint()
    assert key_hint != _SIGNING_KEY
    assert _SIGNING_KEY not in json.dumps(body, sort_keys=True)


async def _append_event(
    event_store: InMemoryOperationalEventPersistence,
    *,
    tenant_id: str,
    sequence: int,
) -> None:
    runtime = OperationalEventRuntime(persistence=event_store)
    await runtime.append_event(
        _event(tenant_id=tenant_id, sequence=sequence),
        expected_tenant_id=tenant_id,
    )


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


def _headers() -> dict[str, str]:
    return {
        "X-Tenant-ID": _TENANT_ID,
        "X-Principal-ID": "principal-ops",
    }


def _window_params() -> dict[str, str]:
    return {
        "from_timestamp": "2026-05-22T00:00:00Z",
        "to_timestamp": "2026-05-24T00:00:00Z",
    }


def _service_override(
    service: AuditExportService,
) -> Callable[[], Awaitable[AuditExportService]]:
    async def override() -> AuditExportService:
        return service

    return override


async def _tenant_scope_override() -> str:
    return _TENANT_ID


def _export_signing_env() -> str:
    return "_".join(("AUDIT", "EXPORT", "HMAC", "SECRET"))


def _key_hint() -> str:
    return hashlib.sha256(_SIGNING_KEY.encode("utf-8")).hexdigest()[:8]
