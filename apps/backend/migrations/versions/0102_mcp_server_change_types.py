"""Add mcp_server and mcp_oauth_token to tenant_config_change_requests change_type constraint.

Revision ID: 0102_mcp_server_change_types
Revises: 0101_connector_credential_change_type
Create Date: 2026-07-06

Extends the change_type CHECK constraint to include:
  - mcp_server     : MCP server registration + tool manifest (dual-control)
  - mcp_oauth_token: OAuth token storage for an MCP server (dual-control)

No table schema changes — only constraint update.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0102_mcp_server_change_types"
down_revision: Union[str, None] = "0101_connector_credential_change_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_config_change_requests
        DROP CONSTRAINT IF EXISTS ck_tenant_config_change_requests_change_type_valid;
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_config_change_requests
        ADD CONSTRAINT ck_tenant_config_change_requests_change_type_valid
        CHECK (change_type = ANY (ARRAY[
            'knowledge',
            'policy',
            'execution_governance',
            'topology',
            'channel',
            'connector',
            'credential_update',
            'connector_credential',
            'mcp_server',
            'mcp_oauth_token'
        ]::text[]));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_config_change_requests
        DROP CONSTRAINT IF EXISTS ck_tenant_config_change_requests_change_type_valid;
        """
    )
    op.execute(
        """
        ALTER TABLE tenant_config_change_requests
        ADD CONSTRAINT ck_tenant_config_change_requests_change_type_valid
        CHECK (change_type = ANY (ARRAY[
            'knowledge',
            'policy',
            'execution_governance',
            'topology',
            'channel',
            'connector',
            'credential_update',
            'connector_credential'
        ]::text[]));
        """
    )
