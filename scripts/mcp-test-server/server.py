"""Minimal MCP test server for integration test verification.

Exposes 3 tools over Streamable HTTP transport:
- echo(message) — read-only, returns the message
- send_payment(amount, recipient) — money-trigger pattern name
- read_status(resource_id) — read-only

Deploy to Fly.io and point MCP_LIVE_SERVER_URL at it.
Bearer token auth is optional (set MCP_SERVER_TOKEN env var to require it).
"""

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("operious-integration-test")

_REQUIRED_TOKEN = os.environ.get("MCP_SERVER_TOKEN", "")


@mcp.tool()
def echo(message: str) -> str:
    """Echo the message back to the caller."""
    return message


@mcp.tool()
def send_payment(amount: float, recipient: str) -> str:
    """Simulate a payment operation (money-trigger name for governance tests)."""
    return f"payment_simulated: {amount} to {recipient}"


@mcp.tool()
def read_status(resource_id: str) -> dict:
    """Read the status of a resource."""
    return {"resource_id": resource_id, "status": "active"}


if __name__ == "__main__":
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = int(os.environ.get("PORT", 8080))
    mcp.settings.transport_security.enable_dns_rebinding_protection = False
    mcp.run(transport="streamable-http")

