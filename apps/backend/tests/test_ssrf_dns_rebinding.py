"""DNS rebinding proofs for the outbound SSRF guard (S-06)."""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpcore
import pytest

from app.boundary.outbound.adapter import (
    OutboundWebhookAdapter,
    OutboundWebhookRequest,
)
from app.core.ssrf import (
    PinnedIPNetworkBackend,
    ValidatedPublicHTTPSURL,
    validate_public_https_url,
)


def test_validator_returns_pinned_ip() -> None:
    def _resolve(host: str, port: int) -> tuple[str, ...]:
        assert host == "webhook.example"
        assert port == 443
        return ("93.184.216.34",)

    validated = validate_public_https_url(
        "https://webhook.example/get",
        resolve=_resolve,
    )

    pinned = ipaddress.ip_address(validated.pinned_ip)
    assert validated.hostname == "webhook.example"
    assert validated.port == 443
    assert isinstance(validated.pinned_ip, str)
    assert not pinned.is_loopback
    assert not pinned.is_link_local
    assert not pinned.is_private
    assert not pinned.is_multicast
    assert not pinned.is_reserved
    assert not pinned.is_unspecified


@pytest.mark.asyncio
async def test_pinned_backend_dials_ip_not_hostname() -> None:
    connections: list[Any] = []

    async def _handle(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        connections.append(writer.get_extra_info("sockname"))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(_handle, "127.0.0.1", 0)
    port = _server_port(server)
    backend = PinnedIPNetworkBackend(pinned_ip="127.0.0.1")
    pool = httpcore.AsyncConnectionPool(network_backend=backend)
    try:
        with pytest.raises(Exception):
            await _core_request(
                pool=pool,
                scheme=b"http",
                host="completely-different-name.invalid",
                port=port,
            )
    finally:
        await pool.aclose()
        await _close_server(server)

    assert len(connections) == 1
    assert connections[0][0] == "127.0.0.1"


@pytest.mark.asyncio
async def test_tls_sni_uses_original_hostname(tmp_path: Path) -> None:
    hostname = "expected-hostname.local"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    sni_seen = asyncio.get_running_loop().create_future()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)

    def _record_sni(
        _ssl_object: ssl.SSLObject,
        server_name: str | None,
        _context: ssl.SSLContext,
    ) -> None:
        if not sni_seen.done():
            sni_seen.set_result(server_name)

    context.set_servername_callback(_record_sni)

    async def _handle(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(
        _handle,
        "127.0.0.1",
        0,
        ssl=context,
    )
    pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl.create_default_context(),
        network_backend=PinnedIPNetworkBackend(pinned_ip="127.0.0.1"),
    )
    try:
        with pytest.raises(Exception):
            await _core_request(
                pool=pool,
                scheme=b"https",
                host=hostname,
                port=_server_port(server),
            )
        assert await asyncio.wait_for(sni_seen, timeout=5.0) == hostname
    finally:
        await pool.aclose()
        await _close_server(server)


@pytest.mark.asyncio
async def test_rebinding_is_architectural() -> None:
    backend = PinnedIPNetworkBackend(pinned_ip="10.0.0.1")
    calls: list[tuple[str, int]] = []

    async def _record_connection(host: str, port: int, **_kwargs: Any) -> None:
        calls.append((host, port))
        raise OSError("connection intentionally refused by test")

    with patch("asyncio.open_connection", _record_connection):
        with pytest.raises(Exception):
            await backend.connect_tcp("example.com", 443, timeout=1.0)

    assert calls == [("10.0.0.1", 443)]


@pytest.mark.asyncio
async def test_adapter_uses_pinned_transport(tmp_path: Path) -> None:
    hostname = "webhook.invalid"
    cert_path, key_path = _generate_self_signed_cert(tmp_path, hostname)
    client_context = ssl.create_default_context(cafile=cert_path)
    client_context.check_hostname = True

    ok_server = await _start_tls_http_server(
        cert_path=cert_path,
        key_path=key_path,
        responses=(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK",
        ),
    )
    adapter = OutboundWebhookAdapter(
        allowed_hosts=(),
        ssl_context=client_context,
        ssrf_validator=_local_validator,
    )
    try:
        ok_response = await adapter.post(
            OutboundWebhookRequest(
                url=f"https://{hostname}:{_server_port(ok_server.server)}/hook",
                payload={"event": "dispatch"},
                auth_header="Bearer token",
                channel_type="jira",
            )
        )
    finally:
        await _close_server(ok_server.server)

    assert ok_response.status_code == 200
    assert ok_response.success
    assert ok_server.hits == 1

    redirect_server = await _start_tls_http_server(
        cert_path=cert_path,
        key_path=key_path,
        responses=(
            b"HTTP/1.1 301 Moved Permanently\r\n"
            b"Location: /second-hop\r\n"
            b"Content-Length: 0\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nFOLLOW",
        ),
    )
    try:
        redirect_response = await adapter.post(
            OutboundWebhookRequest(
                url=(
                    f"https://{hostname}:"
                    f"{_server_port(redirect_server.server)}/hook"
                ),
                payload={"event": "redirect"},
                auth_header="Bearer token",
                channel_type="jira",
            )
        )
        await asyncio.sleep(0)
    finally:
        await _close_server(redirect_server.server)

    assert redirect_response.status_code == 301
    assert not redirect_response.success
    assert redirect_server.hits == 1


async def _core_request(
    *,
    pool: httpcore.AsyncConnectionPool,
    scheme: bytes,
    host: str,
    port: int,
) -> httpcore.Response:
    host_bytes = host.encode("ascii")
    return await pool.handle_async_request(
        httpcore.Request(
            method=b"GET",
            url=httpcore.URL(
                scheme=scheme,
                host=host_bytes,
                port=port,
                target=b"/",
            ),
            headers=[(b"host", host_bytes)],
        )
    )


def _local_validator(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] = (),
) -> ValidatedPublicHTTPSURL:
    del allowed_hosts
    parsed = httpcore.URL(url.encode("ascii"))
    return ValidatedPublicHTTPSURL(
        url=url,
        hostname=parsed.host.decode("ascii"),
        port=parsed.port or 443,
        pinned_ip="127.0.0.1",
    )


class _TLSServer:
    def __init__(self, server: asyncio.AbstractServer) -> None:
        self.server = server
        self.hits = 0


async def _start_tls_http_server(
    *,
    cert_path: str,
    key_path: str,
    responses: tuple[bytes, ...],
) -> _TLSServer:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    tls_server: _TLSServer | None = None
    pending_responses = list(responses)

    async def _handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        assert tls_server is not None
        tls_server.hits += 1
        try:
            await reader.readuntil(b"\r\n\r\n")
            response = (
                pending_responses.pop(0)
                if pending_responses
                else b"HTTP/1.1 500 Internal Server Error\r\n"
                b"Content-Length: 0\r\n\r\n"
            )
            writer.write(response)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(
        _handle,
        "127.0.0.1",
        0,
        ssl=context,
    )
    tls_server = _TLSServer(server)
    return tls_server


def _generate_self_signed_cert(
    tmp_path: Path,
    hostname: str,
) -> tuple[str, str]:
    cert_path = tmp_path / f"{hostname}.crt"
    key_path = tmp_path / f"{hostname}.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-days",
            "1",
            "-nodes",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={hostname}",
            "-addext",
            f"subjectAltName=DNS:{hostname}",
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return str(cert_path), str(key_path)


def _server_port(server: asyncio.AbstractServer) -> int:
    sockets = server.sockets
    assert sockets is not None
    return int(sockets[0].getsockname()[1])


async def _close_server(server: asyncio.AbstractServer) -> None:
    server.close()
    await server.wait_closed()
