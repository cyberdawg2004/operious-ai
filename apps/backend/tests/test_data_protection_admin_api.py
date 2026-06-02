"""Spec 1c-ext data-protection operational admin API."""

from __future__ import annotations

import ast
import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.cognition.db.models import CognitionAuditRecordRow
from app.core.config import get_settings
from app.data_protection.crypto import (
    DataProtectionError,
    DataProtectionService,
    MasterKeyRing,
)
from app.data_protection.db.models import DataProtectionErasureRequestRow
from app.dependencies.authority import (
    TENANT_PRIVACY_ADMIN_CAPABILITY,
    TENANT_PRIVACY_APPROVE_CAPABILITY,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-data-protection-api"
_SUBJECT_ID = "customer-api-001"
_NOW = datetime(2026, 6, 2, 9, tzinfo=timezone.utc)
_MASTER_KEY_BYTES = b"k" * 32
_MASTER_KEY = base64.b64encode(_MASTER_KEY_BYTES).decode("ascii")


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@pytest_asyncio.fixture
async def privacy_client(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    monkeypatch.setenv("DATA_PROTECTION_MASTER_KEYS", "")
    get_settings.cache_clear()
    app = create_app(
        auth_provider=StaticTokenProvider(
            tokens={
                "admin": VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="dpo-a",
                    capabilities=frozenset({TENANT_PRIVACY_ADMIN_CAPABILITY}),
                ),
                "approver": VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="dpo-b",
                    capabilities=frozenset({TENANT_PRIVACY_APPROVE_CAPABILITY}),
                ),
                "same-principal": VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="dpo-a",
                    capabilities=frozenset(
                        {
                            TENANT_PRIVACY_ADMIN_CAPABILITY,
                            TENANT_PRIVACY_APPROVE_CAPABILITY,
                        }
                    ),
                ),
                "no-privacy": VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="viewer",
                    capabilities=frozenset(),
                ),
            }
        )
    )

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
    get_settings.cache_clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _detail(response: httpx.Response) -> object:
    detail = response.json()["detail"]
    if isinstance(detail, str) and detail.startswith("{"):
        return ast.literal_eval(detail)
    return detail


def _service(session: AsyncSession) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(
            keys={"v1": _MASTER_KEY_BYTES},
            active_version="v1",
        ),
    )


def _audit_row(
    *,
    audit_id: uuid.UUID,
    execution_id: str,
    captured_at: datetime,
) -> CognitionAuditRecordRow:
    return CognitionAuditRecordRow(
        audit_id=audit_id,
        tenant_id=_TENANT_ID,
        execution_id=execution_id,
        usage_id=None,
        prompt_full=b"old",
        completion_full=b"old",
        prompt_sha256=hashlib.sha256(f"{execution_id}:prompt".encode()).hexdigest(),
        completion_sha256=hashlib.sha256(
            f"{execution_id}:completion".encode()
        ).hexdigest(),
        model_name="claude-test",
        token_usage={},
        captured_at=captured_at,
    )


async def test_privacy_admin_gate_denies_without_capability(
    privacy_client: httpx.AsyncClient,
) -> None:
    response = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests",
        headers=_headers("no-privacy"),
        json={
            "subject_id": _SUBJECT_ID,
            "reason": "customer GDPR Article 17 request",
        },
    )

    assert response.status_code == 403
    assert _detail(response) == {
        "code": "capability_required",
        "capability": TENANT_PRIVACY_ADMIN_CAPABILITY,
    }


async def test_data_protection_api_returns_503_when_encryption_unconfigured(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", "")
    monkeypatch.setenv("DATA_PROTECTION_MASTER_KEYS", "")
    get_settings.cache_clear()
    app = create_app(
        auth_provider=StaticTokenProvider(
            tokens={
                "admin": VerifiedIdentity(
                    tenant_id=_TENANT_ID,
                    principal_id="dpo-a",
                    capabilities=frozenset({TENANT_PRIVACY_ADMIN_CAPABILITY}),
                )
            }
        )
    )

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/data-protection/erasure-requests",
            headers=_headers("admin"),
            json={
                "subject_id": _SUBJECT_ID,
                "reason": "customer GDPR Article 17 request",
            },
        )

    assert response.status_code == 503
    assert _detail(response) == {"code": "data_protection_not_configured"}
    get_settings.cache_clear()


async def test_erasure_api_propose_then_approve_crypto_shreds(
    privacy_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    marker = await protection.encrypt_text(
        "private customer note",
        tenant_id=_TENANT_ID,
        subject_id=_SUBJECT_ID,
        field="api.subject_note",
    )
    await pg_session.flush()
    assert await protection.decrypt_text(marker) == "private customer note"

    proposed = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests",
        headers=_headers("admin"),
        json={
            "subject_id": _SUBJECT_ID,
            "reason": "customer GDPR Article 17 request",
        },
    )
    assert proposed.status_code == 201
    proposed_body = proposed.json()
    assert proposed_body["status"] == "proposed"
    assert proposed_body["proposed_by"] == "dpo-a"

    approved = await privacy_client.post(
        f"/api/v1/data-protection/erasure-requests/{proposed_body['request_id']}/approve",
        headers=_headers("approver"),
    )

    assert approved.status_code == 200
    approved_body = approved.json()
    assert approved_body["status"] == "executed"
    assert approved_body["approved_by"] == "dpo-b"
    assert approved_body["executed_at"] is not None
    pg_session.expire_all()
    with pytest.raises(DataProtectionError):
        await protection.decrypt_text(marker)


async def test_legal_hold_api_blocks_release_then_allows_erasure(
    privacy_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    protection = _service(pg_session)
    marker = await protection.encrypt_text(
        "held customer note",
        tenant_id=_TENANT_ID,
        subject_id=_SUBJECT_ID,
        field="api.held_subject_note",
    )
    await pg_session.flush()

    hold = await privacy_client.post(
        "/api/v1/data-protection/legal-holds",
        headers=_headers("admin"),
        json={
            "scope": "subject",
            "scope_id": _SUBJECT_ID,
            "reason": "litigation",
        },
    )
    assert hold.status_code == 201
    hold_body = hold.json()
    assert hold_body["created_by"] == "dpo-a"

    listed = await privacy_client.get(
        "/api/v1/data-protection/legal-holds",
        headers=_headers("admin"),
    )
    assert listed.status_code == 200
    assert [item["hold_id"] for item in listed.json()["items"]] == [
        hold_body["hold_id"]
    ]

    blocked_proposal = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests",
        headers=_headers("admin"),
        json={
            "subject_id": _SUBJECT_ID,
            "reason": "customer GDPR Article 17 request",
        },
    )
    assert blocked_proposal.status_code == 201
    blocked_request_id = blocked_proposal.json()["request_id"]
    blocked = await privacy_client.post(
        f"/api/v1/data-protection/erasure-requests/{blocked_request_id}/approve",
        headers=_headers("approver"),
    )
    assert blocked.status_code == 409
    assert _detail(blocked) == {"code": "legal_hold_blocks_erasure"}
    row = (
        await pg_session.execute(
            select(DataProtectionErasureRequestRow).where(
                DataProtectionErasureRequestRow.request_id == uuid.UUID(blocked_request_id)
            )
        )
    ).scalar_one()
    assert row.status == "rejected"
    assert await protection.decrypt_text(marker) == "held customer note"

    released = await privacy_client.delete(
        f"/api/v1/data-protection/legal-holds/{hold_body['hold_id']}",
        headers=_headers("admin"),
    )
    assert released.status_code == 204
    listed_after_release = await privacy_client.get(
        "/api/v1/data-protection/legal-holds",
        headers=_headers("admin"),
    )
    assert listed_after_release.json() == {"items": []}

    allowed_proposal = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests",
        headers=_headers("admin"),
        json={
            "subject_id": _SUBJECT_ID,
            "reason": "customer GDPR Article 17 request after hold release",
        },
    )
    assert allowed_proposal.status_code == 201
    allowed = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests/"
        f"{allowed_proposal.json()['request_id']}/approve",
        headers=_headers("approver"),
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "executed"
    pg_session.expire_all()
    with pytest.raises(DataProtectionError):
        await protection.decrypt_text(marker)


async def test_erasure_api_same_principal_cannot_approve(
    privacy_client: httpx.AsyncClient,
) -> None:
    proposed = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests",
        headers=_headers("same-principal"),
        json={
            "subject_id": _SUBJECT_ID,
            "reason": "customer GDPR Article 17 request",
        },
    )
    assert proposed.status_code == 201

    approved = await privacy_client.post(
        "/api/v1/data-protection/erasure-requests/"
        f"{proposed.json()['request_id']}/approve",
        headers=_headers("same-principal"),
    )

    assert approved.status_code == 403
    assert _detail(approved) == {"code": "erasure_approver_must_differ"}


async def test_retention_policy_api_makes_purge_task_effective(
    privacy_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    await pg_session.merge(TenantRow(tenant_id=_TENANT_ID))
    updated = await privacy_client.put(
        "/api/v1/data-protection/retention-policy",
        headers=_headers("admin"),
        json={"retention_days": 1},
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "tenant_id": _TENANT_ID,
        "retention_days": 1,
    }
    fetched = await privacy_client.get(
        "/api/v1/data-protection/retention-policy",
        headers=_headers("admin"),
    )
    assert fetched.status_code == 200
    assert fetched.json()["retention_days"] == 1

    old_audit_id = uuid.uuid4()
    fresh_audit_id = uuid.uuid4()
    pg_session.add_all(
        [
            _audit_row(
                audit_id=old_audit_id,
                execution_id="api-expired-execution",
                captured_at=_NOW - timedelta(days=5),
            ),
            _audit_row(
                audit_id=fresh_audit_id,
                execution_id="api-fresh-execution",
                captured_at=_NOW,
            ),
        ]
    )
    await pg_session.flush()

    assert await _service(pg_session).purge_expired_cognition_audits(now=_NOW) == 1
    assert await pg_session.get(CognitionAuditRecordRow, old_audit_id) is None
    assert await pg_session.get(CognitionAuditRecordRow, fresh_audit_id) is not None
