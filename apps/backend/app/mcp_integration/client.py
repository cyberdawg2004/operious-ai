"""MCP SDK adapter — the only file allowed to import `mcp` directly.

All `mcp` SDK usage is isolated here. Guarded packages call these
functions; they never import `mcp` themselves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.core.ssrf import ValidatedPublicHTTPSURL


async def fetch_mcp_tools(
    server_url: str,
    *,
    validated: "ValidatedPublicHTTPSURL",
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Fetch the tool manifest from an MCP server.

    ``validated`` is a pre-validated SSRF-safe destination (caller must call
    ``validate_public_https_url`` first).  The httpx client is wired with
    ``PinnedIPAsyncHTTPTransport`` so the TCP connection goes only to the
    pinned IP, preventing SSRF via DNS-rebinding or redirect following.

    Connects via the MCP Streamable HTTP transport, runs the initialize
    handshake, and returns the tool list as plain dicts.
    """
    from app.core.http import create_isolated_http_client
    from app.core.ssrf import PinnedIPAsyncHTTPTransport
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    transport = PinnedIPAsyncHTTPTransport(pinned_ip=validated.pinned_ip)
    http_client = create_isolated_http_client(
        transport=transport,
        timeout_seconds=timeout,
        follow_redirects=False,
    )
    async with streamable_http_client(
        server_url,
        http_client=http_client,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()

    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema.model_dump() if t.inputSchema else {},
        }
        for t in result.tools
    ]


async def invoke_mcp_tool(
    server_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    validated: "ValidatedPublicHTTPSURL",
    auth_headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Invoke a named tool on an MCP server.

    ``validated`` is a pre-validated SSRF-safe destination; the TCP connection
    is pinned to the resolved IP so DNS-rebinding and redirect following are
    closed at the transport layer.

    Returns the raw tool result as a plain dict. Raises on transport error.
    """
    from app.core.http import create_isolated_http_client
    from app.core.ssrf import PinnedIPAsyncHTTPTransport
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    _transport = PinnedIPAsyncHTTPTransport(pinned_ip=validated.pinned_ip)
    _http_client = create_isolated_http_client(
        transport=_transport,
        timeout_seconds=timeout,
        follow_redirects=False,
    )
    extra_headers = auth_headers or {}
    async with streamablehttp_client(
        server_url,
        timeout=timeout,
        headers=extra_headers,
        http_client=_http_client,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            call_result = await session.call_tool(tool_name, arguments=arguments)

    content = call_result.content
    if isinstance(content, list) and content:
        first = content[0]
        if hasattr(first, "text"):
            return {"result": first.text, "is_error": getattr(call_result, "isError", False)}
        if hasattr(first, "data"):
            return {"result": first.data, "is_error": getattr(call_result, "isError", False)}
    return {"result": str(content), "is_error": getattr(call_result, "isError", False)}


def _get_mcp_session_classes() -> tuple[Any, Any]:
    """Return (ClientSession, streamablehttp_client) from the mcp SDK.

    Called by guarded packages that need to use the MCP session directly
    (e.g., for inline error handling) without importing mcp themselves.
    """
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    return ClientSession, streamablehttp_client


__all__ = ["fetch_mcp_tools", "invoke_mcp_tool", "_get_mcp_session_classes"]
