"""Lifecycle-managed outbound HTTP client pool."""

from __future__ import annotations

import httpx

_shared_http_client: httpx.AsyncClient | None = None


def init_shared_http_client(
    *,
    timeout_seconds: float = 30.0,
    max_connections: int = 200,
    max_keepalive_connections: int = 50,
    keepalive_expiry_seconds: float = 30.0,
) -> httpx.AsyncClient:
    """Create or return the shared outbound HTTP client."""

    global _shared_http_client
    if _shared_http_client is not None and not _shared_http_client.is_closed:
        return _shared_http_client
    _shared_http_client = httpx.AsyncClient(
        timeout=timeout_seconds,
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry_seconds,
        ),
    )
    return _shared_http_client


def get_shared_http_client() -> httpx.AsyncClient:
    """Return the shared outbound HTTP client, creating it lazily."""

    return init_shared_http_client()


def create_isolated_http_client(
    *,
    transport: httpx.AsyncBaseTransport,
    timeout_seconds: float,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """Create a short-lived outbound client for custom transports."""

    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout_seconds,
        follow_redirects=follow_redirects,
    )


async def close_shared_http_client() -> None:
    """Close and clear the shared outbound HTTP client."""

    global _shared_http_client
    client = _shared_http_client
    _shared_http_client = None
    if client is not None and not client.is_closed:
        await client.aclose()


__all__ = [
    "close_shared_http_client",
    "create_isolated_http_client",
    "get_shared_http_client",
    "init_shared_http_client",
]
