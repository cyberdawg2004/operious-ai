"""Pydantic schemas for MCP connector API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, field_validator


class McpToolEntry(BaseModel):
    """A single MCP tool declaration in a server registration payload."""

    model_config = ConfigDict(frozen=True)

    tool_name: str
    commitment_kind: str
    execution_policy: str
    description_snapshot: str = ""
    input_schema_snapshot: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class McpServerRegisterRequest(BaseModel):
    """Request body for POST /{tenant_id}/mcp/servers."""

    model_config = ConfigDict(frozen=True)

    mcp_server_id: str
    endpoint_url: str
    mcp_tools: list[McpToolEntry]
    oauth_config: dict[str, Any] | None = None
    timeout_seconds: float = 15.0


class McpToolInfo(BaseModel):
    """A single tool as returned by tools/list from a live MCP server."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class McpToolManifestResponse(BaseModel):
    """Response for GET /{tenant_id}/mcp/servers/{mcp_server_id}/tools."""

    model_config = ConfigDict(frozen=True)

    mcp_server_id: str
    tools: list[McpToolInfo]


class McpOAuthConfig(BaseModel):
    """OAuth configuration for initiating an MCP OAuth dance."""

    model_config = ConfigDict(frozen=True)

    client_id: str
    auth_endpoint: str
    token_endpoint: str
    scopes: list[str] = Field(default_factory=list)
    redirect_uri: str
    client_secret: str = ""

    @field_validator("auth_endpoint", "token_endpoint", mode="before")
    @classmethod
    def _validate_ssrf(cls, v: Any) -> Any:
        from app.core.ssrf import SSRFValidationError, validate_public_https_url

        if not isinstance(v, str):
            return v
        try:
            validate_public_https_url(v)
        except SSRFValidationError as exc:
            raise ValueError(f"OAuth endpoint rejected by SSRF guard: {exc}") from exc
        return v


class McpOAuthStartRequest(BaseModel):
    """Request body for POST /{tenant_id}/mcp/oauth/start."""

    model_config = ConfigDict(frozen=True)

    mcp_server_id: str
    oauth_config: McpOAuthConfig


class McpOAuthStartResponse(BaseModel):
    """Response for POST /{tenant_id}/mcp/oauth/start."""

    model_config = ConfigDict(frozen=True)

    authorization_url: str
    state_token: str


class McpToolPreviewRequest(BaseModel):
    """Request body for POST /{tenant_id}/mcp/preview-tools.

    Fetches a live tool manifest from a raw endpoint URL without requiring
    the server to be registered first. Used by the UI add-server flow.
    """

    model_config = ConfigDict(frozen=True)

    endpoint_url: str
    timeout_seconds: float = 10.0


class McpOAuthCallbackParams:
    """Query parameters for GET /mcp/oauth/callback."""

    def __init__(
        self,
        code: str = Query(..., description="Authorization code from the OAuth provider"),
        state: str = Query(..., description="State token (HMAC-bound)"),
    ) -> None:
        self.code = code
        self.state = state


__all__ = [
    "McpOAuthCallbackParams",
    "McpOAuthStartRequest",
    "McpOAuthStartResponse",
    "McpServerRegisterRequest",
    "McpToolEntry",
    "McpToolInfo",
    "McpToolManifestResponse",
    "McpToolPreviewRequest",
]
