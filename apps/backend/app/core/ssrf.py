"""SSRF guard for tenant-configured outbound URLs (S-06).

Tenant-controlled connector / webhook URLs are attacker-influenced. A
worker that POSTs to one must never be steered at internal services or
cloud metadata. This module enforces, before any connection:

* HTTPS only,
* a present hostname,
* (optional) a SaaS host allowlist,
* DNS resolution where EVERY resolved address is rejected if it is
  loopback / link-local (incl. ``169.254.169.254``) / private /
  reserved / multicast / unspecified — so a public hostname that
  resolves to a private IP (DNS rebinding's first hop) is refused.

Residual: full DNS-rebinding immunity requires pinning the connection
to the validated IP (custom transport). This guard blocks the common
class (internal URL / metadata SSRF) and is the choke point for the
outbound adapter.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from typing import Final
from urllib.parse import urlsplit

_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"https"})

Resolver = Callable[[str, int], Iterable[str]]


class SSRFValidationError(Exception):
    """Raised when an outbound URL is unsafe to dispatch to."""


def _default_resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(
        host, port, proto=socket.IPPROTO_TCP
    )
    return [info[4][0] for info in infos]


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to its v4 form so
    # loopback/private checks apply to the effective destination.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_https_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] = (),
    resolve: Resolver | None = None,
) -> None:
    """Validate ``url`` for safe outbound dispatch.

    Raises :class:`SSRFValidationError` on any unsafe condition. Returns
    ``None`` when the URL is HTTPS, has an allowed host, and resolves
    exclusively to public addresses.
    """

    resolver = resolve or _default_resolve
    parts = urlsplit(url)

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise SSRFValidationError(
            f"scheme {parts.scheme!r} is not allowed; HTTPS is required"
        )
    host = parts.hostname
    if not host:
        raise SSRFValidationError("URL has no host")

    allowlist = {h.lower() for h in allowed_hosts}
    if allowlist and host.lower() not in allowlist:
        raise SSRFValidationError(f"host {host!r} is not in the allowlist")

    try:
        port = parts.port or 443
    except ValueError as exc:  # malformed port
        raise SSRFValidationError("URL has an invalid port") from exc

    try:
        addresses = list(resolver(host, port))
    except OSError as exc:
        raise SSRFValidationError(
            f"DNS resolution failed for {host!r}"
        ) from exc

    if not addresses:
        raise SSRFValidationError(f"{host!r} resolved to no addresses")

    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SSRFValidationError(
                f"{host!r} resolved to an unparseable address {raw!r}"
            ) from exc
        if _is_blocked_ip(ip):
            raise SSRFValidationError(
                f"{host!r} resolves to blocked address {raw}"
            )


__all__ = ["Resolver", "SSRFValidationError", "validate_public_https_url"]
