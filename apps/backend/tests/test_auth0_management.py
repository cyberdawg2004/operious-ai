"""Auth0 Management API integration boundary tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.auth.providers.jwt import TENANT_CONFIG_ADMIN_CAPABILITIES
from app.services.auth0_management import (
    Auth0ManagementClient,
    Auth0ManagementConfig,
    Auth0ManagementProvisioningError,
    TENANT_CONFIG_ADMIN_ROLE,
)

_TENANT_ID = "tenant-auth0-mgmt"
_EMAIL = "owner@example.com"
_NAMESPACE = "https://operious.com"
_ROLE_ID = "rol_tenant_config_admin"
_AUTH0_USER_ID = "auth0|tenant-config-admin"
_TOKEN = "mgmt-token-secret"
_CLIENT_SECRET = "client-secret-value"


@pytest.mark.asyncio
async def test_auth0_management_client_is_idempotent_and_does_not_expose_secrets() -> None:
    calls: list[httpx.Request] = []
    metadata = {
        f"{_NAMESPACE}/tenant_id": _TENANT_ID,
        f"{_NAMESPACE}/roles": [TENANT_CONFIG_ADMIN_ROLE],
        f"{_NAMESPACE}/capabilities": list(TENANT_CONFIG_ADMIN_CAPABILITIES),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/oauth/token":
            payload = json.loads(request.content)
            assert payload["client_secret"] == _CLIENT_SECRET
            return httpx.Response(
                200,
                json={"access_token": _TOKEN, "expires_in": 3600},
            )
        if request.url.path == "/api/v2/users-by-email":
            return httpx.Response(
                200,
                json=[
                    {
                        "user_id": _AUTH0_USER_ID,
                        "email": _EMAIL,
                        "app_metadata": metadata,
                    }
                ],
            )
        if (
            request.url.path.startswith("/api/v2/users/")
            and request.url.path.endswith("/roles")
        ):
            return httpx.Response(
                200,
                json=[{"id": _ROLE_ID, "name": TENANT_CONFIG_ADMIN_ROLE}],
            )
        return httpx.Response(404, json={"error": "unexpected"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http:
        client = Auth0ManagementClient(
            config=_config(),
            http_client=http,
        )
        first = await client.provision_tenant_config_admin(
            tenant_id=_TENANT_ID,
            email=_EMAIL,
        )
        second = await client.provision_tenant_config_admin(
            tenant_id=_TENANT_ID,
            email=_EMAIL,
        )

    assert first.outcome == "already_provisioned"
    assert second.outcome == "already_provisioned"
    assert first.roles_granted == (TENANT_CONFIG_ADMIN_ROLE,)
    assert "tenant.config.approve" not in first.capabilities_granted
    assert [call.url.path for call in calls].count("/oauth/token") == 1
    assert not any(
        call.url.path.endswith("/roles") and call.method == "POST"
        for call in calls
    )
    public_text = f"{first!r} {second!r}"
    assert _TOKEN not in public_text
    assert _CLIENT_SECRET not in public_text
    assert "password" not in public_text.lower()


@pytest.mark.asyncio
async def test_auth0_management_client_refuses_existing_approver_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            return httpx.Response(
                200,
                json={"access_token": _TOKEN, "expires_in": 3600},
            )
        if request.url.path == "/api/v2/users-by-email":
            return httpx.Response(
                200,
                json=[
                    {
                        "user_id": _AUTH0_USER_ID,
                        "email": _EMAIL,
                        "app_metadata": {
                            f"{_NAMESPACE}/tenant_id": _TENANT_ID,
                            f"{_NAMESPACE}/roles": ["TenantApprover"],
                        },
                    }
                ],
            )
        return httpx.Response(404, json={"error": "unexpected"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http:
        client = Auth0ManagementClient(config=_config(), http_client=http)
        with pytest.raises(Auth0ManagementProvisioningError):
            await client.provision_tenant_config_admin(
                tenant_id=_TENANT_ID,
                email=_EMAIL,
            )


def _config() -> Auth0ManagementConfig:
    return Auth0ManagementConfig(
        domain="tenant.auth0.com",
        client_id="client-id",
        client_secret=_CLIENT_SECRET,
        audience="https://tenant.auth0.com/api/v2/",
        connection="Username-Password-Authentication",
        namespace=_NAMESPACE,
        tenant_config_admin_role_id=_ROLE_ID,
    )
