"""Lifecycle-managed outbound HTTP client pool."""

from __future__ import annotations

import asyncio
import logging

import httpx

_shared_http_client: httpx.AsyncClient | None = None
_shared_http_client_loop: asyncio.AbstractEventLoop | None = None
logger = logging.getLogger(__name__)


def init_shared_http_client(
    *,
    timeout_seconds: float = 30.0,
    max_connections: int = 200,
    max_keepalive_connections: int = 50,
    keepalive_expiry_seconds: float = 30.0,
) -> httpx.AsyncClient:
    """Create or return the shared outbound HTTP client.

    Scoped to the CURRENT running event loop, not just the process: callers
    like Celery's diagnostic-agent path run each task attempt through its
    own fresh ``asyncio.run()`` loop (see ``agent_tasks._run_async``), torn
    down when that attempt finishes. An ``httpx.AsyncClient`` cached as a
    bare process global would keep handing back a client whose connection
    pool still references the now-dead loop from a previous attempt — the
    next attempt's pool housekeeping (closing an idle/expired keepalive
    connection) then calls back into that dead loop and raises
    ``RuntimeError: Event loop is closed``. Recreating whenever the running
    loop differs from the one the cached client was built under avoids
    that: the orphaned client is simply dropped, never closed from the
    wrong loop.
    """

    global _shared_http_client, _shared_http_client_loop
    try:
        current_loop: asyncio.AbstractEventLoop | None = (
            asyncio.get_running_loop()
        )
    except RuntimeError:
        current_loop = None
    if (
        _shared_http_client is not None
        and not _shared_http_client.is_closed
        and _shared_http_client_loop is current_loop
    ):
        return _shared_http_client
    _shared_http_client = httpx.AsyncClient(
        timeout=timeout_seconds,
        limits=httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=keepalive_expiry_seconds,
        ),
    )
    _shared_http_client_loop = current_loop
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

    global _shared_http_client, _shared_http_client_loop
    client = _shared_http_client
    _shared_http_client = None
    _shared_http_client_loop = None
    if client is not None and not client.is_closed:
        try:
            await client.aclose()
        except RuntimeError as exc:
            if "Event loop is closed" not in str(exc):
                raise
            logger.warning("shared_http_client_close_skipped_closed_loop")


__all__ = [
    "close_shared_http_client",
    "create_isolated_http_client",
    "get_shared_http_client",
    "init_shared_http_client",
]
