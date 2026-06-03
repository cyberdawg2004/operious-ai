"""connector config reconstruction binding

Revision ID: 0071_connector_config_reconstruction
Revises: 0070_connector_configs
Create Date: 2026-06-04
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0071_connector_config_reconstruction"
down_revision: Union[str, None] = "0070_connector_configs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONNECTOR_TABLE = "connector_configs"
_CHANGE_REQUEST_TABLE = "tenant_config_change_requests"
_LEGACY_APPROVAL_ID = "legacy-bootstrap"
_LEGACY_CONFIGURED_BY = "legacy-bootstrap"
_LEGACY_CONTENT_SHA256 = "0" * 64


def upgrade() -> None:
    op.add_column(
        _CONNECTOR_TABLE,
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        schema="public",
    )
    op.add_column(
        _CONNECTOR_TABLE,
        sa.Column(
            "configured_by",
            sa.String(length=255),
            server_default=sa.text(f"'{_LEGACY_CONFIGURED_BY}'"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        _CONNECTOR_TABLE,
        sa.Column(
            "source_approval_id",
            sa.String(length=255),
            server_default=sa.text(f"'{_LEGACY_APPROVAL_ID}'"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        _CONNECTOR_TABLE,
        sa.Column(
            "content_sha256",
            sa.String(length=64),
            server_default=sa.text(f"'{_LEGACY_CONTENT_SHA256}'"),
            nullable=False,
        ),
        schema="public",
    )
    op.add_column(
        _CONNECTOR_TABLE,
        sa.Column("previous_version_sha256", sa.String(length=64), nullable=True),
        schema="public",
    )

    op.drop_constraint(
        op.f("uq_connector_configs_tenant_tool_name"),
        _CONNECTOR_TABLE,
        type_="unique",
        schema="public",
    )
    op.drop_constraint(
        op.f("pk_connector_configs"),
        _CONNECTOR_TABLE,
        type_="primary",
        schema="public",
    )
    op.create_primary_key(
        op.f("pk_connector_configs"),
        _CONNECTOR_TABLE,
        ["tenant_id", "connector_type", "tool_name", "version"],
        schema="public",
    )
    op.create_unique_constraint(
        op.f("uq_connector_configs_tenant_tool_version"),
        _CONNECTOR_TABLE,
        ["tenant_id", "tool_name", "version"],
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_connector_configs_version_positive"),
        _CONNECTOR_TABLE,
        "version >= 1",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_connector_configs_configured_by_nonempty"),
        _CONNECTOR_TABLE,
        "length(configured_by) > 0",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_connector_configs_source_approval_id_nonempty"),
        _CONNECTOR_TABLE,
        "length(source_approval_id) > 0",
        schema="public",
    )
    op.create_check_constraint(
        op.f("ck_connector_configs_content_sha256_len"),
        _CONNECTOR_TABLE,
        "length(content_sha256) = 64",
        schema="public",
    )
    op.create_index(
        op.f("ix_connector_configs_source_approval_id"),
        _CONNECTOR_TABLE,
        ["source_approval_id"],
        schema="public",
    )

    _drop_change_type_constraint()
    op.create_check_constraint(
        "change_type_valid",
        _CHANGE_REQUEST_TABLE,
        (
            "change_type IN ("
            "'knowledge', 'policy', 'execution_governance', "
            "'topology', 'channel', 'connector'"
            ")"
        ),
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint("change_type_valid", _CHANGE_REQUEST_TABLE, type_="check")
    op.create_check_constraint(
        op.f("ck_tenant_config_change_requests_change_type_valid"),
        _CHANGE_REQUEST_TABLE,
        (
            "change_type IN ("
            "'knowledge', 'policy', 'execution_governance', "
            "'topology', 'channel'"
            ")"
        ),
        schema="public",
    )

    op.drop_index(
        op.f("ix_connector_configs_source_approval_id"),
        table_name=_CONNECTOR_TABLE,
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_connector_configs_content_sha256_len"),
        _CONNECTOR_TABLE,
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_connector_configs_source_approval_id_nonempty"),
        _CONNECTOR_TABLE,
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_connector_configs_configured_by_nonempty"),
        _CONNECTOR_TABLE,
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        op.f("ck_connector_configs_version_positive"),
        _CONNECTOR_TABLE,
        type_="check",
        schema="public",
    )
    op.drop_constraint(
        op.f("uq_connector_configs_tenant_tool_version"),
        _CONNECTOR_TABLE,
        type_="unique",
        schema="public",
    )
    op.drop_constraint(
        op.f("pk_connector_configs"),
        _CONNECTOR_TABLE,
        type_="primary",
        schema="public",
    )
    op.create_primary_key(
        op.f("pk_connector_configs"),
        _CONNECTOR_TABLE,
        ["tenant_id", "connector_type", "tool_name"],
        schema="public",
    )
    op.create_unique_constraint(
        op.f("uq_connector_configs_tenant_tool_name"),
        _CONNECTOR_TABLE,
        ["tenant_id", "tool_name"],
        schema="public",
    )
    op.drop_column(_CONNECTOR_TABLE, "previous_version_sha256", schema="public")
    op.drop_column(_CONNECTOR_TABLE, "content_sha256", schema="public")
    op.drop_column(_CONNECTOR_TABLE, "source_approval_id", schema="public")
    op.drop_column(_CONNECTOR_TABLE, "configured_by", schema="public")
    op.drop_column(_CONNECTOR_TABLE, "version", schema="public")


def _drop_change_type_constraint() -> None:
    op.execute(
        """
        ALTER TABLE public.tenant_config_change_requests
        DROP CONSTRAINT IF EXISTS change_type_valid
        """
    )
    op.execute(
        """
        ALTER TABLE public.tenant_config_change_requests
        DROP CONSTRAINT IF EXISTS ck_tenant_config_change_requests_change_type_valid
        """
    )
