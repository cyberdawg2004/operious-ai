"""SSRF guard for tenant-configured outbound URLs (S-06).

Tenant-controlled connector / webhook URLs are attacker-influenced. A
worker that POSTs to one must never be steered at internal services or
cloud metadata. This module enforces, before any connection:

* HTTPS only,
* a present hostname,
* (optional) a SaaS host allowlist,
* DNS resolution where EVERY resolved address is rejected if it is
  loopback / link-local (incl. ``169.254.169.254``) / private /
  reserved / multicast / unspecified,
* a pinned, validated IP for the outbound transport to dial directly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Protocol, cast
from urllib.parse import urlsplit

import httpcore
import httpx

_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"https"})

Resolver = Callable[[str, int], Iterable[str]]


@dataclass(frozen=True, slots=True)
class ValidatedPublicHTTPSURL:
    """Safe outbound destination after resolve-validate-pin."""

    url: str
    hostname: str
    port: int
    pinned_ip: str


class SSRFValidationError(Exception):
    """Raised when an outbound URL is unsafe to dispatch to."""


class PinnedIPNetworkBackend(httpcore.AsyncNetworkBackend):
    """httpcore network backend that dials a pre-validated IP only."""

    def __init__(self, *, pinned_ip: str) -> None:
        ipaddress.ip_address(pinned_ip)
        self._pinned_ip = pinned_ip

    @property
    def pinned_ip(self) -> str:
        return self._pinned_ip

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del host
        kwargs: dict[str, Any] = {}
        if local_address is not None:
            kwargs["local_addr"] = (local_address, 0)
        try:
            reader, writer = await _with_timeout(
                asyncio.open_connection(self._pinned_ip, port, **kwargs),
                timeout,
            )
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout from exc
        except OSError as exc:
            raise httpcore.ConnectError(str(exc)) from exc

        if socket_options is not None:
            sock = writer.get_extra_info("socket")
            if sock is not None:
                for option in socket_options:
                    sock.setsockopt(*option)
        return _AsyncioNetworkStream(reader=reader, writer=writer)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        del path, timeout, socket_options
        raise httpcore.UnsupportedProtocol("Unix sockets are not supported")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class PinnedIPAsyncHTTPTransport(httpx.AsyncBaseTransport):
    """httpx transport that keeps URL host/SNI but dials the pinned IP."""

    def __init__(
        self,
        *,
        pinned_ip: str,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context or ssl.create_default_context(),
            max_connections=1,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=PinnedIPNetworkBackend(pinned_ip=pinned_ip),
        )

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = await self._pool.handle_async_request(core_request)
        core_extensions = cast(dict[str, Any], cast(Any, core_response).extensions)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_HttpCoreResponseStream(
                cast(_ClosableAsyncByteStream, core_response.stream)
            ),
            extensions=core_extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def _default_resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


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
) -> ValidatedPublicHTTPSURL:
    """Validate ``url`` and return the pinned outbound destination.

    Raises :class:`SSRFValidationError` on any unsafe condition.
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
        raise SSRFValidationError(f"DNS resolution failed for {host!r}") from exc

    if not addresses:
        raise SSRFValidationError(f"{host!r} resolved to no addresses")

    pinned_ip: str | None = None
    for raw in addresses:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise SSRFValidationError(
                f"{host!r} resolved to an unparseable address {raw!r}"
            ) from exc
        if _is_blocked_ip(ip):
            raise SSRFValidationError(f"{host!r} resolves to blocked address {raw}")
        if pinned_ip is None:
            pinned_ip = str(ip)

    if pinned_ip is None:
        raise SSRFValidationError(f"{host!r} resolved to no usable addresses")

    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=host,
        port=port,
        pinned_ip=pinned_ip,
    )


class _AsyncioNetworkStream(httpcore.AsyncNetworkStream):
    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._reader = reader
        self._writer = writer

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        try:
            return await _with_timeout(self._reader.read(max_bytes), timeout)
        except TimeoutError as exc:
            raise httpcore.ReadTimeout from exc
        except OSError as exc:
            raise httpcore.ReadError(str(exc)) from exc

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        if not buffer:
            return
        try:
            self._writer.write(buffer)
            await _with_timeout(self._writer.drain(), timeout)
        except TimeoutError as exc:
            raise httpcore.WriteTimeout from exc
        except OSError as exc:
            raise httpcore.WriteError(str(exc)) from exc

    async def aclose(self) -> None:
        self._writer.close()
        await self._writer.wait_closed()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            await _with_timeout(
                self._writer.start_tls(
                    ssl_context,
                    server_hostname=server_hostname,
                ),
                timeout,
            )
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout from exc
        except (OSError, ssl.SSLError) as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        return self

    def get_extra_info(self, info: str) -> Any:
        return self._writer.get_extra_info(info)


class _ClosableAsyncByteStream(Protocol):
    def __aiter__(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None: ...


class _HttpCoreResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: _ClosableAsyncByteStream) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._stream:
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


async def _with_timeout[T](
    awaitable: Awaitable[T],
    timeout: float | None,
) -> T:
    if timeout is None:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout)


__all__ = [
    "PinnedIPAsyncHTTPTransport",
    "PinnedIPNetworkBackend",
    "Resolver",
    "SSRFValidationError",
    "ValidatedPublicHTTPSURL",
    "validate_public_https_url",
]
