"""HTTP wrapper break-controls for OMS credential self-service.

Verifies the browser-facing route is a thin wrapper over
TenantConfigChangeRequestService.propose_oms_credential_update():
  * write-capability gated
  * dual-control remains enforced
  * API never returns credentials
  * pending change-request stores only the sentinel
  * tenant_channel_configurations.credentials_enc stores OPCRED2 ciphertext
"""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import VerifiedIdentity
from app.auth.providers import StaticTokenProvider
from app.core.config import get_settings
from app.dependencies.database import get_db_session
from app.main import create_app
from app.tenant.credentials import is_opcred2
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-oms-http-route"
_OMS_TOOL = "refund.request"
_WRITE_ONLY = "tenant.connector.write"
_CONFIG_APPROVE = "tenant.config.approve"
_MASTER_KEY = "oms-http-route-master-key-32-bytes!"
_PROPOSER_TOKEN = "tenant-oms-http-route-proposer"
_PROPOSER_APPROVER_TOKEN = "tenant-oms-http-route-same-principal"
_APPROVER_TOKEN = "tenant-oms-http-route-approver"
_EMPTY_TOKEN = "tenant-oms-http-route-empty"
_BEARER_CREDS: dict[str, Any] = {
    "auth_type": "bearer",
    "token": "tok_http_route_secret",
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _detail(response: httpx.Response) -> object:
    detail = response.json()["detail"]
    if isinstance(detail, str) and detail.startswith("{"):
        return ast.literal_eval(detail)
    return detail


async def _seed_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text(
            "INSERT INTO tenants (tenant_id, status) VALUES (:tenant_id, 'active') "
            "ON CONFLICT DO NOTHING"
        ),
        {"tenant_id": tenant_id},
    )


@asynccontextmanager
async def _tenant_client(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    get_settings.cache_clear()
    provider = StaticTokenProvider(
        tokens={
            _PROPOSER_TOKEN: VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-proposer",
                capabilities=frozenset({_WRITE_ONLY}),
            ),
            _PROPOSER_APPROVER_TOKEN: VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-same",
                capabilities=frozenset({_WRITE_ONLY, _CONFIG_APPROVE}),
            ),
            _APPROVER_TOKEN: VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-approver",
                capabilities=frozenset({_CONFIG_APPROVE}),
            ),
            _EMPTY_TOKEN: VerifiedIdentity(
                tenant_id=_TENANT_ID,
                principal_id="principal-empty",
                capabilities=frozenset(),
            ),
        }
    )
    app = create_app(auth_provider=cast(Any, provider))

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override_db

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client
    finally:
        get_settings.cache_clear()


def _payload_from_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        mapping = cast(Mapping[object, Any], value)
        return {str(key): item for key, item in mapping.items()}
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            mapping = cast(Mapping[object, Any], loaded)
            return {str(key): item for key, item in mapping.items()}
    raise AssertionError(f"unexpected proposed_payload type: {type(value)!r}")


@pytest.mark.asyncio
async def test_http_oms_credentials_create_pending_redacted_request(
    pg_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session, _TENANT_ID)

    async with _tenant_client(pg_session, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/tenant/{_TENANT_ID}/connectors/{_OMS_TOOL}/credentials",
            headers=_headers(_PROPOSER_TOKEN),
            json=_BEARER_CREDS,
        )

    assert response.status_code == 204
    assert response.content == b""
    assert _BEARER_CREDS["token"] not in response.text
    assert _BEARER_CREDS["token"] not in caplog.text

    change_row = (
        await pg_session.execute(
            text(
                """
                SELECT change_request_id, change_type, proposed_payload
                FROM tenant_config_change_requests
                WHERE tenant_id = :tenant_id
                ORDER BY proposed_at DESC
                LIMIT 1
                """
            ),
            {"tenant_id": _TENANT_ID},
        )
    ).one()
    assert change_row.change_type == "credential_update"
    payload = _payload_from_row(change_row.proposed_payload)
    assert payload["channel"] == TenantChannelType.OMS.value
    assert isinstance(payload["credential_hash"], str)
    assert len(payload["credential_hash"]) == 64
    assert set(payload) == {"_schema_version", "channel", "credential_hash"}
    assert "token" not in payload
    assert "api_key" not in payload
    assert "username" not in payload
    assert "password" not in payload

    channel_row = (
        await pg_session.execute(
            text(
                """
                SELECT credentials_enc, status
                FROM tenant_channel_configurations
                WHERE tenant_id = :tenant_id
                  AND channel_type = :channel_type
                """
            ),
            {
                "tenant_id": _TENANT_ID,
                "channel_type": TenantChannelType.OMS.value,
            },
        )
    ).one()
    ciphertext = bytes(channel_row.credentials_enc)
    assert channel_row.status == TenantChannelStatus.PENDING_VALIDATION.value
    assert is_opcred2(ciphertext)
    assert _BEARER_CREDS["token"].encode() not in ciphertext


@pytest.mark.asyncio
async def test_http_oms_credentials_require_connector_write_capability(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session, _TENANT_ID)

    async with _tenant_client(pg_session, monkeypatch) as client:
        response = await client.post(
            f"/api/v1/tenant/{_TENANT_ID}/connectors/{_OMS_TOOL}/credentials",
            headers=_headers(_EMPTY_TOKEN),
            json=_BEARER_CREDS,
        )

    assert response.status_code == 403
    assert "tok_http_route_secret" not in response.text


@pytest.mark.asyncio
async def test_http_oms_credentials_preserve_dual_control(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    await _seed_tenant(pg_session, _TENANT_ID)

    async with _tenant_client(pg_session, monkeypatch) as client:
        propose = await client.post(
            f"/api/v1/tenant/{_TENANT_ID}/connectors/{_OMS_TOOL}/credentials",
            headers=_headers(_PROPOSER_APPROVER_TOKEN),
            json=_BEARER_CREDS,
        )
        assert propose.status_code == 204

        change_request_id = (
            await pg_session.execute(
                text(
                    """
                    SELECT change_request_id
                    FROM tenant_config_change_requests
                    WHERE tenant_id = :tenant_id
                    ORDER BY proposed_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": _TENANT_ID},
            )
        ).scalar_one()

        approve = await client.post(
            f"/api/v1/tenant/config/change-requests/{change_request_id}/approve",
            headers=_headers(_PROPOSER_APPROVER_TOKEN),
        )

    assert approve.status_code == 403
    assert _detail(approve) == {"code": "tenant_config_approver_must_differ"}
