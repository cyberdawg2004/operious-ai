"""Domain capability split for tenant configuration mutations (PR_SEC-B4)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from starlette.testclient import TestClient

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.auth.providers.jwt import (
    DEFAULT_CLAIM_MAPPING,
    extract_capabilities_from_claims,
)
from app.core.config import get_settings
from app.dependencies.authority import (
    TENANT_CHANNEL_ADMIN_CAPABILITY,
    TENANT_CONFIG_APPROVE_CAPABILITY,
    TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES,
    TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY,
    TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TENANT_POLICY_WRITE_CAPABILITY,
    TENANT_TOPOLOGY_WRITE_CAPABILITY,
)
from app.dependencies.services import (
    get_tenant_config_change_request_service,
    get_tenant_configuration_service,
)
from app.main import create_app
from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import (
    derive_channel_configuration_id,
    derive_governance_policy_id,
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)

_TENANT_ID = "tenant-acme"
_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)
_DOMAIN_CAPABILITIES = {
    TENANT_CHANNEL_ADMIN_CAPABILITY,
    TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TENANT_POLICY_WRITE_CAPABILITY,
    TENANT_TOPOLOGY_WRITE_CAPABILITY,
    TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY,
}


class _FakeTenantConfigurationService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def configure_channel(
        self,
        *,
        tenant_id: str,
        channel_type: TenantChannelType,
        routing_address: str,
        credentials: dict[str, Any],
        webhook_secret: str,
        status: TenantChannelStatus,
    ) -> TenantChannelConfigurationRecord:
        self.calls.append("channel")
        return TenantChannelConfigurationRecord(
            config_id=derive_channel_configuration_id(
                tenant_id=tenant_id,
                channel_type=channel_type,
            ),
            tenant_id=tenant_id,
            channel_type=channel_type,
            status=status,
            routing_address=routing_address,
            credentials_enc=b"redacted",
            webhook_secret=webhook_secret,
            verified_at=None,
            created_at=_NOW,
            updated_at=_NOW,
        )

    async def create_knowledge_document(
        self,
        *,
        tenant_id: str,
        title: str,
        content: str,
        document_type: TenantKnowledgeDocumentType,
        status: TenantKnowledgeDocumentStatus,
        uploaded_by: str,
    ) -> TenantKnowledgeDocumentRecord:
        self.calls.append("knowledge")
        return TenantKnowledgeDocumentRecord(
            document_id=derive_knowledge_document_id(
                tenant_id=tenant_id,
                title=title,
                document_type=document_type,
            ),
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=document_type,
            status=status,
            version=1,
            uploaded_by=uploaded_by,
            vector_indexed_at=None,
            created_at=_NOW,
            review_status=TenantKnowledgeReviewStatus.QUARANTINED,
        )

    async def create_governance_policy(
        self,
        *,
        tenant_id: str,
        policy_type: str,
        parameters: dict[str, Any],
        status: TenantGovernancePolicyStatus,
        approved_by: str,
        effective_from: datetime,
    ) -> TenantGovernancePolicyRecord:
        self.calls.append("policy")
        return TenantGovernancePolicyRecord(
            policy_id=derive_governance_policy_id(
                tenant_id=tenant_id,
                policy_type=policy_type,
            ),
            tenant_id=tenant_id,
            policy_type=policy_type,
            parameters=parameters,
            status=status,
            version=1,
            approved_by=approved_by,
            effective_from=effective_from,
            created_at=_NOW,
            source_approval_id="test-approval",
            content_sha256="sha256",
            previous_version_sha256=None,
        )


class _FakeChangeRequestService:
    def __init__(self) -> None:
        self.proposals: list[TenantConfigChangeType] = []

    async def propose(
        self,
        *,
        tenant_id: str,
        change_type: TenantConfigChangeType,
        payload: dict[str, Any],
        proposed_by: str,
    ) -> TenantConfigChangeRequestRecord:
        self.proposals.append(change_type)
        return TenantConfigChangeRequestRecord(
            change_request_id=uuid.uuid4(),
            tenant_id=tenant_id,
            change_type=change_type,
            proposed_payload={"_schema_version": "1", **payload},
            status=TenantConfigChangeRequestStatus.PROPOSED,
            proposed_by=proposed_by,
            proposed_at=_NOW,
        )


@dataclass(frozen=True, slots=True)
class _Harness:
    client: TestClient
    config_service: _FakeTenantConfigurationService
    change_service: _FakeChangeRequestService


@pytest.fixture
def domain_client(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("TENANT_CONFIG_ALLOW_SELF_APPROVAL", "true")
    get_settings.cache_clear()
    provider = StaticTokenProvider(
        tokens={
            "channel": _identity(TENANT_CHANNEL_ADMIN_CAPABILITY),
            "knowledge": _identity(TENANT_KNOWLEDGE_WRITE_CAPABILITY),
            "policy": _identity(TENANT_POLICY_WRITE_CAPABILITY),
            "empty": _identity(),
            "admin": _identity(*TENANT_CONFIG_DOMAIN_WRITE_CAPABILITIES),
        }
    )
    config_service = _FakeTenantConfigurationService()
    change_service = _FakeChangeRequestService()
    app = create_app(auth_provider=provider)
    app.dependency_overrides[get_tenant_configuration_service] = (
        lambda: config_service
    )
    app.dependency_overrides[get_tenant_config_change_request_service] = (
        lambda: change_service
    )
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield _Harness(
            client=client,
            config_service=config_service,
            change_service=change_service,
        )
    finally:
        get_settings.cache_clear()


def test_channel_route_requires_channel_capability(
    domain_client: _Harness,
) -> None:
    ok = domain_client.client.post(
        "/api/v1/tenant/channels",
        headers=_headers("channel"),
        json=_channel_payload(),
    )
    denied = domain_client.client.post(
        "/api/v1/tenant/channels",
        headers=_headers("knowledge"),
        json=_channel_payload(),
    )

    assert ok.status_code == 200
    assert denied.status_code == 403
    assert TENANT_CHANNEL_ADMIN_CAPABILITY in denied.text
    assert domain_client.config_service.calls == ["channel"]


def test_policy_route_requires_policy_capability(domain_client: _Harness) -> None:
    ok = domain_client.client.post(
        "/api/v1/tenant/policies",
        headers=_headers("policy"),
        json=_policy_payload(),
    )
    denied = domain_client.client.post(
        "/api/v1/tenant/policies",
        headers=_headers("channel"),
        json=_policy_payload(),
    )

    assert ok.status_code == 200
    assert denied.status_code == 403
    assert TENANT_POLICY_WRITE_CAPABILITY in denied.text
    assert domain_client.config_service.calls == ["policy"]


def test_knowledge_route_requires_knowledge_capability(
    domain_client: _Harness,
) -> None:
    ok = domain_client.client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers("knowledge"),
        json=_knowledge_payload(),
    )
    denied = domain_client.client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers("channel"),
        json=_knowledge_payload(),
    )

    assert ok.status_code == 200
    assert denied.status_code == 403
    assert TENANT_KNOWLEDGE_WRITE_CAPABILITY in denied.text
    assert domain_client.config_service.calls == ["knowledge"]


def test_channel_admin_cannot_write_policy(domain_client: _Harness) -> None:
    response = domain_client.client.post(
        "/api/v1/tenant/config/change-requests",
        headers=_headers("channel"),
        json={
            "change_type": "policy",
            "payload": _policy_payload(),
        },
    )

    assert response.status_code == 403
    assert TENANT_POLICY_WRITE_CAPABILITY in response.text
    assert domain_client.change_service.proposals == []


def test_channel_admin_can_propose_channel_change_request(
    domain_client: _Harness,
) -> None:
    response = domain_client.client.post(
        "/api/v1/tenant/config/change-requests",
        headers=_headers("channel"),
        json={
            "change_type": "channel",
            "payload": _channel_payload(),
        },
    )

    assert response.status_code == 201
    assert domain_client.change_service.proposals == [
        TenantConfigChangeType.CHANNEL
    ]


def test_channel_admin_cannot_write_knowledge_direct_or_propose(
    domain_client: _Harness,
) -> None:
    direct = domain_client.client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers("channel"),
        json=_knowledge_payload(),
    )
    proposed = domain_client.client.post(
        "/api/v1/tenant/config/change-requests",
        headers=_headers("channel"),
        json={
            "change_type": "knowledge",
            "payload": _knowledge_payload(),
        },
    )

    assert direct.status_code == 403
    assert proposed.status_code == 403
    assert TENANT_KNOWLEDGE_WRITE_CAPABILITY in direct.text
    assert TENANT_KNOWLEDGE_WRITE_CAPABILITY in proposed.text
    assert domain_client.config_service.calls == []
    assert domain_client.change_service.proposals == []


def test_auth0_role_maps_to_domain_capabilities() -> None:
    aggregate = _capabilities_for_roles("TenantConfigAdmin")
    legacy_aggregate = _capabilities_for_roles("TenantAdmin")
    granular = _capabilities_for_roles(
        "TenantChannelAdmin",
        "TenantKnowledgeWriter",
        "TenantPolicyWriter",
        "TenantTopologyWriter",
        "TenantExecGovWriter",
    )
    approver = _capabilities_for_roles("TenantApprover")

    assert _DOMAIN_CAPABILITIES.issubset(aggregate)
    assert _DOMAIN_CAPABILITIES.issubset(legacy_aggregate)
    assert "tenant_admin" not in legacy_aggregate
    assert _DOMAIN_CAPABILITIES.issubset(granular)
    assert approver == frozenset({TENANT_CONFIG_APPROVE_CAPABILITY})


def _identity(*capabilities: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        tenant_id=_TENANT_ID,
        principal_id="principal-test",
        capabilities=frozenset(capabilities),
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _channel_payload() -> dict[str, Any]:
    return {
        "channel_type": "email",
        "routing_address": "support@example.com",
        "credentials": {"api_key": "secret"},
        "webhook_secret": "webhook",
    }


def _knowledge_payload() -> dict[str, Any]:
    return {
        "title": "Warranty FAQ",
        "content": "Warranty requests require proof of purchase.",
        "document_type": "faq",
    }


def _policy_payload() -> dict[str, Any]:
    return {
        "policy_type": "refund_limit",
        "parameters": {"max_refund_usd": 50},
        "effective_from": _NOW.isoformat(),
    }


def _capabilities_for_roles(*roles: str) -> frozenset[str]:
    return extract_capabilities_from_claims(
        claims={"sub": "principal-test", "roles": list(roles)},
        claim_mapping=DEFAULT_CLAIM_MAPPING,
    )
