"""MCP SDK isolation wrapper.

All direct imports of the `mcp` third-party SDK are confined to this package.
Constitutional / infrastructure code (agents, api, services, workers, etc.)
MUST NOT import `mcp` directly — they call the adapter functions here instead.
This keeps the guarded package graph free of the transitional vendor SDK.
"""
from app.mcp_integration.client import fetch_mcp_tools, invoke_mcp_tool

__all__ = ["fetch_mcp_tools", "invoke_mcp_tool"]
