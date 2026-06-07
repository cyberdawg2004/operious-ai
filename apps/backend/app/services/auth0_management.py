"""Auth0 Management API client for platform identity provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import secrets
import time
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from app.auth.providers.jwt import ROLE_CAPABILITY_MAP
from app.core.config import Settings

TENANT_CONFIG_ADMIN_ROLE = "TenantConfigAdmin"
TENANT_APPROVER_ROLE = "TenantApprover"


class Auth0ManagementError(RuntimeError):
    """Base class for Auth0 Management API integration failures."""


class Auth0ManagementConfigurationError(Auth0ManagementError):
    """Raised when the Management API client is not configured."""


class Auth0ManagementProvisioningError(Auth0ManagementError):
    """Raised when Auth0 refuses or cannot complete provisioning."""


@dataclass(frozen=True, slots=True)
class Auth0TenantAdminProvisioningResult:
    tenant_id: str
    email: str
    auth0_user_id: str
    roles_granted: tuple[str, ...]
    capabilities_granted: tuple[str, ...]
    created_user: bool
    updated_claims: bool
    assigned_roles: bool
    outcome: str
    provisioned_at: datetime


class Auth0ManagementClientProtocol(Protocol):
    async def provision_tenant_config_admin(
        self,
        *,
        tenant_id: str,
        email: str,
    ) -> Auth0TenantAdminProvisioningResult:
        """Create/ensure a tenant config admin in Auth0."""
        ...


@dataclass(frozen=True, slots=True)
class Auth0ManagementConfig:
    domain: str
    client_id: str
    client_secret: str
    audience: str
    connection: str
    namespace: str
    tenant_config_admin_role_id: str

    @classmethod
    def from_settings(cls, settings: Settings) -> "Auth0ManagementConfig":
        domain = _domain_from_settings(settings)
        if not domain:
            raise Auth0ManagementConfigurationError(
                "AUTH0_DOMAIN or AUTH0_ISSUER is required for Auth0 Management"
            )
        if not settings.AUTH0_MGMT_CLIENT_ID:
            raise Auth0ManagementConfigurationError(
                "AUTH0_MGMT_CLIENT_ID is required for Auth0 Management"
            )
        if not settings.AUTH0_MGMT_CLIENT_SECRET:
            raise Auth0ManagementConfigurationError(
                "AUTH0_MGMT_CLIENT_SECRET is required for Auth0 Management"
            )
        if not settings.AUTH0_MGMT_CONNECTION:
            raise Auth0ManagementConfigurationError(
                "AUTH0_MGMT_CONNECTION is required for tenant admin provisioning"
            )
        if not settings.AUTH0_TENANT_CONFIG_ADMIN_ROLE_ID:
            raise Auth0ManagementConfigurationError(
                "AUTH0_TENANT_CONFIG_ADMIN_ROLE_ID is required for tenant admin provisioning"
            )
        audience = settings.AUTH0_MGMT_AUDIENCE or f"https://{domain}/api/v2/"
        return cls(
            domain=domain,
            client_id=settings.AUTH0_MGMT_CLIENT_ID,
            client_secret=settings.AUTH0_MGMT_CLIENT_SECRET,
            audience=audience,
            connection=settings.AUTH0_MGMT_CONNECTION,
            namespace=settings.AUTH0_NAMESPACE.rstrip("/"),
            tenant_config_admin_role_id=settings.AUTH0_TENANT_CONFIG_ADMIN_ROLE_ID,
        )


class Auth0ManagementClient:
    """Minimal Auth0 Management API client for tenant admin provisioning."""

    def __init__(
        self,
        *,
        config: Auth0ManagementConfig,
        http_client: httpx.AsyncClient,
        clock: object | None = None,
    ) -> None:
        self._config = config
        self._http = http_client
        self._base_url = f"https://{config.domain}"
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._clock = clock

    async def provision_tenant_config_admin(
        self,
        *,
        tenant_id: str,
        email: str,
    ) -> Auth0TenantAdminProvisioningResult:
        canonical_email = _canonical_email(email)
        role_names = (TENANT_CONFIG_ADMIN_ROLE,)
        capabilities = _capabilities_for_roles(*role_names)
        metadata = self._desired_app_metadata(
            tenant_id=tenant_id,
            roles=role_names,
            capabilities=capabilities,
        )

        user, created_user = await self._get_or_create_user(
            email=canonical_email,
            app_metadata=metadata,
        )
        auth0_user_id = _user_id(user)
        existing_metadata = _app_metadata(user)
        self._assert_safe_existing_metadata(
            existing_metadata,
            tenant_id=tenant_id,
        )
        merged_metadata = self._merge_app_metadata(
            existing=existing_metadata,
            desired=metadata,
        )
        updated_claims = False
        if merged_metadata != existing_metadata:
            patched_user = await self._request_json(
                "PATCH",
                f"/api/v2/users/{quote(auth0_user_id, safe='')}",
                json={"app_metadata": merged_metadata},
            )
            if not isinstance(patched_user, dict):
                raise Auth0ManagementProvisioningError(
                    "Auth0 update user response was not an object"
                )
            user = cast(dict[str, Any], patched_user)
            updated_claims = True

        existing_roles = await self._user_roles(auth0_user_id)
        if any(role.get("name") == TENANT_APPROVER_ROLE for role in existing_roles):
            raise Auth0ManagementProvisioningError(
                "refusing to provision config admin onto an existing TenantApprover"
            )
        existing_role_ids = {
            str(role.get("id"))
            for role in existing_roles
            if isinstance(role.get("id"), str)
        }
        assigned_roles = False
        if self._config.tenant_config_admin_role_id not in existing_role_ids:
            await self._request_json(
                "POST",
                f"/api/v2/users/{quote(auth0_user_id, safe='')}/roles",
                json={"roles": [self._config.tenant_config_admin_role_id]},
            )
            assigned_roles = True

        return Auth0TenantAdminProvisioningResult(
            tenant_id=tenant_id,
            email=canonical_email,
            auth0_user_id=auth0_user_id,
            roles_granted=role_names,
            capabilities_granted=capabilities,
            created_user=created_user,
            updated_claims=updated_claims,
            assigned_roles=assigned_roles,
            outcome=(
                "already_provisioned"
                if not created_user and not updated_claims and not assigned_roles
                else "provisioned"
            ),
            provisioned_at=_now_utc(self._clock),
        )

    async def _get_or_create_user(
        self,
        *,
        email: str,
        app_metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        users_payload = await self._request_json(
            "GET",
            "/api/v2/users-by-email",
            params={"email": email},
        )
        if not isinstance(users_payload, list):
            raise Auth0ManagementProvisioningError(
                "Auth0 users-by-email response was not a list"
            )
        for item in cast(list[object], users_payload):
            if not isinstance(item, dict):
                continue
            user = cast(dict[str, Any], item)
            if str(user.get("email", "")).strip().lower() == email:
                return user, False

        password = secrets.token_urlsafe(32)
        user_payload = await self._request_json(
            "POST",
            "/api/v2/users",
            json={
                "connection": self._config.connection,
                "email": email,
                "password": password,
                "verify_email": True,
                "app_metadata": app_metadata,
            },
        )
        if not isinstance(user_payload, dict):
            raise Auth0ManagementProvisioningError(
                "Auth0 create user response was not an object"
            )
        user = cast(dict[str, Any], user_payload)
        return user, True

    async def _user_roles(self, auth0_user_id: str) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            f"/api/v2/users/{quote(auth0_user_id, safe='')}/roles",
        )
        if not isinstance(payload, list):
            raise Auth0ManagementProvisioningError(
                "Auth0 user roles response was not a list"
            )
        roles: list[dict[str, Any]] = []
        for item in cast(list[object], payload):
            if isinstance(item, dict):
                roles.append(cast(dict[str, Any], item))
        return roles

    def _desired_app_metadata(
        self,
        *,
        tenant_id: str,
        roles: tuple[str, ...],
        capabilities: tuple[str, ...],
    ) -> dict[str, Any]:
        namespace = self._config.namespace
        return {
            f"{namespace}/tenant_id": tenant_id,
            f"{namespace}/roles": list(roles),
            f"{namespace}/capabilities": list(capabilities),
        }

    def _assert_safe_existing_metadata(
        self,
        metadata: dict[str, Any],
        *,
        tenant_id: str,
    ) -> None:
        namespace = self._config.namespace
        existing_tenant = metadata.get(f"{namespace}/tenant_id")
        if existing_tenant is not None and existing_tenant != tenant_id:
            raise Auth0ManagementProvisioningError(
                "refusing to re-scope an existing Auth0 user to another tenant"
            )
        existing_roles = _string_set(metadata.get(f"{namespace}/roles"))
        existing_capabilities = _string_set(
            metadata.get(f"{namespace}/capabilities")
        )
        if (
            TENANT_APPROVER_ROLE in existing_roles
            or "tenant.config.approve" in existing_capabilities
        ):
            raise Auth0ManagementProvisioningError(
                "refusing to provision config admin onto an existing approver"
            )

    def _merge_app_metadata(
        self,
        *,
        existing: dict[str, Any],
        desired: dict[str, Any],
    ) -> dict[str, Any]:
        namespace = self._config.namespace
        merged = dict(existing)
        merged[f"{namespace}/tenant_id"] = desired[f"{namespace}/tenant_id"]
        for key in (f"{namespace}/roles", f"{namespace}/capabilities"):
            existing_values = _string_set(existing.get(key))
            desired_values = _string_set(desired[key])
            if desired_values.issubset(existing_values):
                merged[key] = existing.get(key)
            else:
                merged[key] = _ordered_union(desired[key], existing.get(key))
        return merged

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> object:
        token = await self._management_token()
        response = await self._http.request(
            method,
            f"{self._base_url}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            raise Auth0ManagementProvisioningError(
                f"Auth0 Management API request failed: {response.status_code}"
            )
        if not response.content:
            return None
        return cast(object, response.json())

    async def _management_token(self) -> str:
        now = _now_epoch(self._clock)
        if self._token and now < self._token_expires_at - 60:
            return self._token
        response = await self._http.post(
            f"{self._base_url}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "audience": self._config.audience,
            },
        )
        if response.status_code >= 400:
            raise Auth0ManagementProvisioningError(
                f"Auth0 Management token request failed: {response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise Auth0ManagementProvisioningError(
                "Auth0 Management token response was not an object"
            )
        token_payload = cast(dict[str, Any], payload)
        token = token_payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise Auth0ManagementProvisioningError(
                "Auth0 Management token response did not include access_token"
            )
        expires_in = token_payload.get("expires_in")
        expires_seconds = (
            float(expires_in) if isinstance(expires_in, (int, float)) else 3600.0
        )
        self._token = token
        self._token_expires_at = now + expires_seconds
        return token


def build_auth0_management_client(
    *,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> Auth0ManagementClient | None:
    try:
        config = Auth0ManagementConfig.from_settings(settings)
    except Auth0ManagementConfigurationError:
        return None
    return Auth0ManagementClient(config=config, http_client=http_client)


def _capabilities_for_roles(*roles: str) -> tuple[str, ...]:
    values: list[str] = []
    for role in roles:
        mapped = ROLE_CAPABILITY_MAP[role]
        if isinstance(mapped, str):
            if mapped not in values:
                values.append(mapped)
        else:
            for value in mapped:
                if value not in values:
                    values.append(value)
    return tuple(values)


def _domain_from_settings(settings: Settings) -> str | None:
    if settings.AUTH0_DOMAIN:
        return settings.AUTH0_DOMAIN.strip().removeprefix("https://").removeprefix(
            "http://"
        ).rstrip("/")
    if settings.AUTH0_ISSUER:
        return settings.AUTH0_ISSUER.strip().removeprefix("https://").removeprefix(
            "http://"
        ).rstrip("/")
    return None


def _canonical_email(email: str) -> str:
    value = email.strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise Auth0ManagementProvisioningError("email is invalid")
    return value


def _app_metadata(user: dict[str, Any]) -> dict[str, Any]:
    metadata = user.get("app_metadata")
    if not isinstance(metadata, dict):
        return {}
    return {str(key): value for key, value in cast(dict[object, Any], metadata).items()}


def _user_id(user: dict[str, Any]) -> str:
    value = user.get("user_id")
    if not isinstance(value, str) or not value:
        raise Auth0ManagementProvisioningError("Auth0 user_id missing")
    return value


def _string_set(value: object) -> set[str]:
    return set(_string_items(value))


def _string_items(value: object) -> list[str]:
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [
            item
            for item in cast(list[object], value)
            if isinstance(item, str) and item
        ]
    if isinstance(value, tuple):
        return [
            item
            for item in cast(tuple[object, ...], value)
            if isinstance(item, str) and item
        ]
    return []


def _ordered_union(*values: object) -> list[str]:
    ordered: list[str] = []
    for value in values:
        for item in _string_items(value):
            if item not in ordered:
                ordered.append(item)
    return ordered


def _now_utc(clock: object | None) -> datetime:
    if clock is None:
        return datetime.now(UTC)
    now = getattr(clock, "now")
    value = now(UTC)
    return cast(datetime, value)


def _now_epoch(clock: object | None) -> float:
    if clock is None:
        return time.time()
    now = getattr(clock, "time")
    return float(now())


__all__ = [
    "Auth0ManagementClient",
    "Auth0ManagementClientProtocol",
    "Auth0ManagementConfig",
    "Auth0ManagementConfigurationError",
    "Auth0ManagementError",
    "Auth0ManagementProvisioningError",
    "Auth0TenantAdminProvisioningResult",
    "TENANT_CONFIG_ADMIN_ROLE",
    "TENANT_APPROVER_ROLE",
    "build_auth0_management_client",
]
