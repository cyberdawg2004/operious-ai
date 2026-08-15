"""Production security posture derived from settings (S-01, S-08).

Pins:

* legacy header authority is disabled by default in production and
  enabled otherwise, with an explicit override,
* ``TRUSTED_PROXIES`` parses into IP networks,
* ``resolved_trusted_proxies`` returns ``None`` only for non-production
  deployments that pinned nothing (legacy/test behaviour), and a
  concrete (possibly empty) tuple in production,
* ``select_auth_provider`` maps the namespaced Auth0 tenant /
  organization / environment / capability claims, not bare names.
"""

from __future__ import annotations

from ipaddress import ip_network

from app.core.config import Settings
from app.main import select_auth_provider


# ─── Legacy header authority posture ─────────────────────────────────


def test_legacy_header_authority_enabled_by_default_non_production() -> None:
    assert Settings(ENVIRONMENT="local").legacy_header_authority_enabled is True
    assert (
        Settings(ENVIRONMENT="staging").legacy_header_authority_enabled is True
    )


def test_legacy_header_authority_disabled_by_default_in_production() -> None:
    assert (
        Settings(ENVIRONMENT="production").legacy_header_authority_enabled
        is False
    )


def test_legacy_header_authority_explicit_override_wins() -> None:
    enabled = Settings(
        ENVIRONMENT="production",
        LEGACY_HEADER_AUTHORITY_ENABLED=True,
    )
    assert enabled.legacy_header_authority_enabled is True
    disabled = Settings(
        ENVIRONMENT="local",
        LEGACY_HEADER_AUTHORITY_ENABLED=False,
    )
    assert disabled.legacy_header_authority_enabled is False


# ─── Trusted proxy parsing ───────────────────────────────────────────


def test_trusted_proxies_parsed_into_networks() -> None:
    s = Settings(TRUSTED_PROXIES="10.0.0.0/8, 192.168.1.5")
    assert s.trusted_proxy_networks == (
        ip_network("10.0.0.0/8"),
        ip_network("192.168.1.5/32"),
    )


def test_resolved_trusted_proxies_none_for_non_production_empty() -> None:
    assert Settings(ENVIRONMENT="local").resolved_trusted_proxies is None


def test_resolved_trusted_proxies_empty_tuple_for_production_empty() -> None:
    assert Settings(ENVIRONMENT="production").resolved_trusted_proxies == ()


def test_resolved_trusted_proxies_uses_pinned_networks() -> None:
    s = Settings(ENVIRONMENT="production", TRUSTED_PROXIES="172.16.0.0/12")
    assert s.resolved_trusted_proxies == (ip_network("172.16.0.0/12"),)


# ─── Auth0 namespaced claim mapping (S-08) ───────────────────────────


def test_select_auth_provider_maps_namespaced_tenant_claim() -> None:
    settings = Settings(
        AUTH_ENABLED=True,
        AUTH_PROVIDER="auth0",
        AUTH0_DOMAIN="example.auth0.com",
        AUTH0_ISSUER="https://example.auth0.com/",
        AUTH0_AUDIENCE="https://api.operious.ai",
        AUTH0_JWKS_URL="https://example.auth0.com/.well-known/jwks.json",
        AUTH0_NAMESPACE="https://operious.com",
    )
    provider = select_auth_provider(settings)
    assert provider is not None
    mapping = provider._claim_mapping  # type: ignore[attr-defined]
    assert mapping.tenant_id == "https://operious.com/tenant_id"
    assert mapping.organization_id == "https://operious.com/org_id"
    assert mapping.environment_id == "https://operious.com/env"
    assert mapping.capabilities == "https://operious.com/capabilities"
    assert mapping.roles_claim == "https://operious.com/roles"
    # The standard subject claim stays canonical (never namespaced).
    assert mapping.principal_id == "sub"
