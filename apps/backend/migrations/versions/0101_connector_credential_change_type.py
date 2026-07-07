"""Add connector_credential to tenant_config_change_requests change_type constraint.

Revision ID: 0101_connector_credential_change_type
Revises: 0100_connector_credentials_table
Create Date: 2026-07-05

"""

from __future__ import annotations

from alembic import op

revision = "0101_connector_credential_change_type"
down_revision = "0100_connector_credentials_table"
branch_labels = None
depends_on = None


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
            'connector_credential'
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
            'credential_update'
        ]::text[]));
        """
    )
