"""Spec 1a-ext object RBAC sweep invariants."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid
from typing import Any, cast

import pytest
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from app.agents.tools.approvals import ActionApprovalRecord
from app.auth import AuthProvider, VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.core.config import get_settings
from app.dependencies.authority import (
    TENANT_ACTIONS_APPROVE_CAPABILITY,
    TENANT_COGNITION_READ_CAPABILITY,
    TENANT_GOVERNANCE_READ_CAPABILITY,
    TENANT_KNOWLEDGE_APPROVE_CAPABILITY,
    TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TENANT_OBSERVABILITY_READ_CAPABILITY,
    TENANT_OPERATIONS_READ_CAPABILITY,
    TENANT_PRIVACY_ADMIN_CAPABILITY,
    TENANT_PRIVACY_APPROVE_CAPABILITY,
    TENANT_SUPERVISOR_READ_CAPABILITY,
    TENANT_TRAINING_WRITE_CAPABILITY,
)
from app.dependencies.services import (
    get_action_approval_service,
    get_cognition_service,
    get_data_protection_service,
    get_governance_repository,
    get_operational_event_service,
    get_quarantine_service,
    get_supervisor_inbox_service,
    get_trainer_recommendation_service,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from app.data_protection.crypto import (
    DataProtectionErasureRequestRecord,
    ErasureRequestStatus,
)
from app.services.quarantine_service import SemanticQuarantineRecord
from app.trainer.records import TrainingRecommendationRecord

_TENANT_ID = "tenant-acme"
_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

# Tenant-scoped routes listed here are non-operator ingress surfaces where
# tenant scope is the object boundary; adding a row requires doctrine review.
_TENANT_SCOPE_ONLY_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "POST",
        "/api/v1/boundary/work-orders/fulfillment",
    ): "tenant-owned inbound status callback; tenant scope is the object bound",
}

_SWEEP_ROUTER_MODULES = {
    "app.api.v1.routers.action_approvals",
    "app.api.v1.routers.arbitration",
    "app.api.v1.routers.boundary",
    "app.api.v1.routers.cognition",
    "app.api.v1.routers.coordination",
    "app.api.v1.routers.crisis",
    "app.api.v1.routers.data_protection",
    "app.api.v1.routers.escalation",
    "app.api.v1.routers.governance",
    "app.api.v1.routers.operational_events",
    "app.api.v1.routers.queue_operations",
    "app.api.v1.routers.quota_operations",
    "app.api.v1.routers.semantic",
    "app.api.v1.routers.session",
    "app.api.v1.routers.sop_intelligence",
    "app.api.v1.routers.supervisor",
    "app.api.v1.routers.trainer",
}

_CAPABILITY_DEP_NAMES = {
    "require_operator_authority",
    "require_tenant_actions_approve",
    "require_tenant_admin",
    "require_tenant_audit_export",
    "require_tenant_cognition_read",
    "require_tenant_connector_read",
    "require_tenant_governance_read",
    "require_tenant_knowledge_approve",
    "require_tenant_knowledge_write",
    "require_tenant_observability_read",
    "require_tenant_operations_read",
    "require_tenant_privacy_admin",
    "require_tenant_privacy_approve",
    "require_tenant_supervisor_read",
    "require_tenant_training_write",
}


@pytest.fixture(autouse=True)
def _test_settings(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_every_tenant_scoped_route_has_object_rbac_gate() -> None:
    app = create_app()
    missing: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.endpoint.__module__ not in _SWEEP_ROUTER_MODULES:
            continue
        dep_calls = _dependency_calls(route)
        if not _has_dependency(dep_calls, "require_tenant_scope"):
            continue
        for method in sorted(route.methods or ()):
            if method == "HEAD":
                continue
            key = (method, route.path)
            if _has_capability_gate(dep_calls):
                continue
            if key in _TENANT_SCOPE_ONLY_ALLOWLIST:
                continue
            missing.append(f"{method} {route.path}")
    assert not missing, "Tenant-scoped routes missing object RBAC: " + repr(missing)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            "operations",
            id="tenant.operations.read",
        ),
        pytest.param(
            "supervisor",
            id="tenant.supervisor.read",
        ),
        pytest.param(
            "governance",
            id="tenant.governance.read",
        ),
        pytest.param(
            "cognition",
            id="tenant.cognition.read",
        ),
        pytest.param(
            "observability",
            id="tenant.observability.read",
        ),
        pytest.param(
            "actions",
            id="tenant.actions.approve",
        ),
        pytest.param(
            "knowledge",
            id="tenant.knowledge.write",
        ),
        pytest.param(
            "training",
            id="tenant.training.write",
        ),
        pytest.param(
            "privacy_admin",
            id="tenant.privacy.admin",
        ),
        pytest.param(
            "privacy_approve",
            id="tenant.privacy.approve",
        ),
    ],
)
def test_capability_gate_denies_without_and_allows_with(case: str) -> None:
    spec = _CAPABILITY_CASES[case]
    denied = _request(spec, capabilities=())
    _assert_capability_required(denied, capability=spec.capability)

    allowed = _request(spec, capabilities=(spec.capability,))
    assert allowed.status_code == 200


def test_operator_bundle_cannot_approve_actions_without_action_approver() -> None:
    from app.auth.providers.jwt import ROLE_CAPABILITY_MAP

    spec = _CAPABILITY_CASES["actions"]
    operator_caps = tuple(ROLE_CAPABILITY_MAP["Operator"])

    denied = _request(spec, capabilities=operator_caps)
    _assert_capability_required(
        denied,
        capability=TENANT_ACTIONS_APPROVE_CAPABILITY,
    )

    allowed = _request(spec, capabilities=(TENANT_ACTIONS_APPROVE_CAPABILITY,))
    assert allowed.status_code == 200


def test_operator_bundle_excludes_separation_of_duties_capabilities() -> None:
    from app.auth.providers.jwt import ROLE_CAPABILITY_MAP

    operator_caps = set(ROLE_CAPABILITY_MAP["Operator"])
    assert TENANT_GOVERNANCE_READ_CAPABILITY not in operator_caps
    assert TENANT_COGNITION_READ_CAPABILITY not in operator_caps
    assert TENANT_ACTIONS_APPROVE_CAPABILITY not in operator_caps
    assert TENANT_TRAINING_WRITE_CAPABILITY not in operator_caps
    assert TENANT_PRIVACY_ADMIN_CAPABILITY not in operator_caps
    assert TENANT_PRIVACY_APPROVE_CAPABILITY not in operator_caps


@dataclass(frozen=True, slots=True)
class _CapabilityCase:
    capability: str
    method: str
    path: str
    overrides: Callable[[Any], None]
    json: dict[str, Any] | None = None


def _install_fake_data_protection(app: Any) -> None:
    app.dependency_overrides.update(
        {
            get_data_protection_service: lambda: _FakeDataProtectionService(),
            get_db_session: _fake_db_session,
        }
    )


_CAPABILITY_CASES: dict[str, _CapabilityCase] = {
    "operations": _CapabilityCase(
        capability=TENANT_OPERATIONS_READ_CAPABILITY,
        method="GET",
        path="/api/v1/approvals/actions",
        overrides=lambda app: app.dependency_overrides.update(
            {get_action_approval_service: lambda: _FakeActionApprovalService()}
        ),
    ),
    "supervisor": _CapabilityCase(
        capability=TENANT_SUPERVISOR_READ_CAPABILITY,
        method="GET",
        path="/api/v1/supervisor/inspections",
        overrides=lambda app: app.dependency_overrides.update(
            {get_supervisor_inbox_service: lambda: _FakeSupervisorInboxService()}
        ),
    ),
    "governance": _CapabilityCase(
        capability=TENANT_GOVERNANCE_READ_CAPABILITY,
        method="GET",
        path="/api/v1/governance/decisions",
        overrides=lambda app: app.dependency_overrides.update(
            {get_governance_repository: lambda: _FakeGovernanceRepository()}
        ),
    ),
    "cognition": _CapabilityCase(
        capability=TENANT_COGNITION_READ_CAPABILITY,
        method="GET",
        path="/api/v1/cognition/knowledge/versions",
        overrides=lambda app: app.dependency_overrides.update(
            {get_cognition_service: lambda: _FakeCognitionService()}
        ),
    ),
    "observability": _CapabilityCase(
        capability=TENANT_OBSERVABILITY_READ_CAPABILITY,
        method="GET",
        path="/api/v1/operational-events",
        overrides=lambda app: app.dependency_overrides.update(
            {get_operational_event_service: lambda: _FakeOperationalEventService()}
        ),
    ),
    "actions": _CapabilityCase(
        capability=TENANT_ACTIONS_APPROVE_CAPABILITY,
        method="POST",
        path="/api/v1/approvals/actions/approval-1/approve",
        json={"note": "approved"},
        overrides=lambda app: app.dependency_overrides.update(
            {get_action_approval_service: lambda: _FakeActionApprovalService()}
        ),
    ),
    "knowledge": _CapabilityCase(
        capability=TENANT_KNOWLEDGE_WRITE_CAPABILITY,
        method="POST",
        path="/api/v1/semantic/quarantine/quarantine-1/release",
        json={"verdict": "false_positive", "note": "reviewed"},
        overrides=lambda app: app.dependency_overrides.update(
            {get_quarantine_service: lambda: _FakeQuarantineService()}
        ),
    ),
    "training": _CapabilityCase(
        capability=TENANT_TRAINING_WRITE_CAPABILITY,
        method="PATCH",
        path="/api/v1/trainer/recommendations/recommendation-1",
        json={"status": "acknowledged"},
        overrides=lambda app: app.dependency_overrides.update(
            {get_trainer_recommendation_service: lambda: _FakeTrainerService()}
        ),
    ),
    "privacy_admin": _CapabilityCase(
        capability=TENANT_PRIVACY_ADMIN_CAPABILITY,
        method="GET",
        path="/api/v1/data-protection/legal-holds",
        overrides=_install_fake_data_protection,
    ),
    "privacy_approve": _CapabilityCase(
        capability=TENANT_PRIVACY_APPROVE_CAPABILITY,
        method="POST",
        path=(
            "/api/v1/data-protection/erasure-requests/"
            "00000000-0000-0000-0000-000000000101/approve"
        ),
        overrides=_install_fake_data_protection,
    ),
}


def _request(
    spec: _CapabilityCase,
    *,
    capabilities: tuple[str, ...],
) -> Any:
    token = "with-capability" if capabilities else "without-capability"
    auth_provider = cast(
        AuthProvider,
        StaticTokenProvider(
            tokens={
                token: VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="principal-test",
                    capabilities=frozenset(capabilities),
                )
            }
        ),
    )
    app = create_app(auth_provider=auth_provider)
    spec.overrides(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.request(
            spec.method,
            spec.path,
            headers={"Authorization": f"Bearer {token}"},
            json=spec.json,
        )


def _assert_capability_required(response: Any, *, capability: str) -> None:
    assert response.status_code == 403
    detail = response.json()["detail"]
    if isinstance(detail, str):
        assert "capability_required" in detail
        assert capability in detail
        return
    assert detail == {
        "code": "capability_required",
        "capability": capability,
    }


def _dependency_calls(route: APIRoute) -> tuple[Callable[..., Any], ...]:
    calls: list[Callable[..., Any]] = []

    def visit(dependant: Any) -> None:
        call = getattr(dependant, "call", None)
        if callable(call):
            calls.append(call)
        for child in getattr(dependant, "dependencies", ()):
            visit(child)

    visit(route.dependant)
    return tuple(calls)


def _has_dependency(
    calls: tuple[Callable[..., Any], ...],
    name: str,
) -> bool:
    return any(getattr(call, "__name__", "") == name for call in calls)


def _has_capability_gate(calls: tuple[Callable[..., Any], ...]) -> bool:
    for call in calls:
        name = getattr(call, "__name__", "")
        qualname = getattr(call, "__qualname__", "")
        if name in _CAPABILITY_DEP_NAMES:
            return True
        if qualname.startswith("require_capability.<locals>."):
            return True
        if qualname.startswith("require_config_apply_authorization_for.<locals>."):
            return True
    return False


class _FakeActionApprovalService:
    async def list_by_status(self, **_: Any) -> list[ActionApprovalRecord]:
        return []

    async def approve(self, **_: Any) -> ActionApprovalRecord:
        return _action_approval_record(status="approved")


class _FakeSupervisorInboxService:
    async def list_inspections(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            items=(),
            total=0,
            offset=kwargs.get("offset", 0),
            limit=kwargs.get("limit", 25),
        )


class _FakeGovernanceRepository:
    async def query_decisions(self, _: Any) -> SimpleNamespace:
        return SimpleNamespace(items=(), total=0, offset=0)


class _FakeCognitionService:
    async def list_document_versions(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            items=(),
            total=0,
            offset=kwargs.get("offset", 0),
        )


class _FakeOperationalEventService:
    async def list_events(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            events=(),
            total=0,
            limit=kwargs.get("limit", 100),
            offset=kwargs.get("offset", 0),
        )


class _FakeQuarantineService:
    async def release(self, **_: Any) -> SemanticQuarantineRecord:
        return SemanticQuarantineRecord(
            quarantine_id="quarantine-1",
            tenant_id=_TENANT_ID,
            channel="ticket",
            original_queue="queue",
            external_id="external-1",
            ticket_payload_json={},
            fingerprint_json=[],
            cluster_size=1,
            similarity_threshold=0.9,
            status="false_positive",
            reviewed_by="principal-test",
            reviewed_at=_NOW,
            resolution_note="reviewed",
            created_at=_NOW,
            metadata={},
        )


class _FakeTrainerService:
    async def update_status(self, **_: Any) -> TrainingRecommendationRecord:
        return TrainingRecommendationRecord(
            recommendation_id="recommendation-1",
            tenant_id=_TENANT_ID,
            session_id="00000000-0000-0000-0000-000000000001",
            qa_score_id="00000000-0000-0000-0000-000000000002",
            category="diagnostic_accuracy",
            finding_summary="summary",
            recommendation="recommendation",
            priority="medium",
            status="acknowledged",
            created_at=_NOW,
        )


class _FakeDataProtectionService:
    async def list_legal_holds(self, **_: Any) -> tuple[Any, ...]:
        return ()

    async def approve_erasure(self, **_: Any) -> DataProtectionErasureRequestRecord:
        return DataProtectionErasureRequestRecord(
            request_id=uuid.UUID("00000000-0000-0000-0000-000000000101"),
            tenant_id=_TENANT_ID,
            subject_id="subject-1",
            reason="test approval",
            status=ErasureRequestStatus.EXECUTED,
            proposed_by="principal-proposer",
            proposed_at=_NOW,
            approved_by="principal-test",
            approved_at=_NOW,
            executed_at=_NOW,
        )


class _FakeDBSession:
    async def commit(self) -> None:
        return None


async def _fake_db_session() -> AsyncIterator[_FakeDBSession]:
    yield _FakeDBSession()


def _action_approval_record(*, status: str) -> ActionApprovalRecord:
    return ActionApprovalRecord(
        approval_id="approval-1",
        tenant_id=_TENANT_ID,
        session_id="00000000-0000-0000-0000-000000000003",
        execution_id=None,
        tool_name="refund",
        idempotency_key="00000000-0000-0000-0000-000000000004",
        payload_json={},
        governance_decision_id=None,
        status=status,
        requested_at=_NOW,
        resolved_at=_NOW if status != "pending" else None,
        resolved_by="principal-test" if status != "pending" else None,
        resolution_note="approved" if status != "pending" else None,
        metadata={},
    )
