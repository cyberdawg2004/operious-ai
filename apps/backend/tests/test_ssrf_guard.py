"""SSRF guard for tenant-configured outbound URLs (S-06).

Tenant-controlled webhook / connector URLs must never let a worker
reach loopback, link-local (incl. cloud metadata 169.254.169.254),
private, or reserved addresses, and must be HTTPS. DNS is resolved and
EVERY resolved address is checked so a public hostname that resolves to
a private IP is rejected.
"""

from __future__ import annotations

import pytest

from app.core.ssrf import SSRFValidationError, validate_public_https_url


def _resolve_to(*addresses: str):
    def _resolver(host: str, port: int) -> list[str]:
        del host, port
        return list(addresses)

    return _resolver


def test_https_public_address_is_allowed() -> None:
    validate_public_https_url(
        "https://hooks.example.com/x", resolve=_resolve_to("93.184.216.34")
    )


def test_http_scheme_rejected() -> None:
    with pytest.raises(SSRFValidationError):
        validate_public_https_url(
            "http://hooks.example.com/x", resolve=_resolve_to("93.184.216.34")
        )


def test_missing_host_rejected() -> None:
    with pytest.raises(SSRFValidationError):
        validate_public_https_url("https:///path", resolve=_resolve_to("8.8.8.8"))


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.10",  # private
        "172.16.0.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "::1",  # ipv6 loopback
        "fd00::1",  # ipv6 ULA (private)
        "fe80::1",  # ipv6 link-local
        "0.0.0.0",  # unspecified
        "::ffff:127.0.0.1",  # ipv4-mapped loopback
    ],
)
def test_blocked_addresses_rejected(addr: str) -> None:
    with pytest.raises(SSRFValidationError):
        validate_public_https_url(
            "https://hooks.example.com/x", resolve=_resolve_to(addr)
        )


def test_any_private_resolution_rejects_even_with_public_sibling() -> None:
    # Public hostname resolving to BOTH a public and a private address.
    with pytest.raises(SSRFValidationError):
        validate_public_https_url(
            "https://rebind.example.com/x",
            resolve=_resolve_to("93.184.216.34", "10.0.0.5"),
        )


def test_allowlist_blocks_unlisted_host() -> None:
    with pytest.raises(SSRFValidationError):
        validate_public_https_url(
            "https://evil.example.com/x",
            allowed_hosts=("hooks.example.com",),
            resolve=_resolve_to("93.184.216.34"),
        )


def test_allowlist_permits_listed_host() -> None:
    validate_public_https_url(
        "https://hooks.example.com/x",
        allowed_hosts=("hooks.example.com",),
        resolve=_resolve_to("93.184.216.34"),
    )


def test_dns_failure_rejected() -> None:
    def _boom(host: str, port: int) -> list[str]:
        raise OSError("dns down")

    with pytest.raises(SSRFValidationError):
        validate_public_https_url("https://x.example.com/", resolve=_boom)


def test_literal_loopback_ip_rejected_with_real_resolver() -> None:
    # No injected resolver: exercises the default getaddrinfo path with a
    # literal IP (deterministic, no network).
    with pytest.raises(SSRFValidationError):
        validate_public_https_url("https://127.0.0.1/")


@pytest.mark.asyncio
async def test_outbound_adapter_rejects_private_url_before_network() -> None:
    from app.boundary.outbound.adapter import (
        OutboundWebhookAdapter,
        OutboundWebhookRequest,
    )

    adapter = OutboundWebhookAdapter(allowed_hosts=())
    with pytest.raises(SSRFValidationError):
        await adapter.post(
            OutboundWebhookRequest(
                url="https://127.0.0.1/hook",
                payload={"a": 1},
                auth_header="Bearer x",
                channel_type="jira",
            )
        )


@pytest.mark.asyncio
async def test_outbound_adapter_rejects_http_metadata_endpoint() -> None:
    from app.boundary.outbound.adapter import (
        OutboundWebhookAdapter,
        OutboundWebhookRequest,
    )

    adapter = OutboundWebhookAdapter(allowed_hosts=())
    with pytest.raises(SSRFValidationError):
        await adapter.post(
            OutboundWebhookRequest(
                url="http://169.254.169.254/latest/meta-data/",
                payload={},
                auth_header="Bearer x",
                channel_type="jira",
            )
        )
