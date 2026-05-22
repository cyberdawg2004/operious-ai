"""create tenant topology configuration table (Phase 4-B)

Revision ID: 0019_tenant_topology_config
Revises: 0018_approval_records
Create Date: 2026-05-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_tenant_topology_config"
down_revision: Union[str, None] = "0018_approval_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_topology_configurations",
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("topology_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column(
            "topology",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configured_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(tenant_id) > 0",
            name=op.f("ck_tenant_topology_configurations_tenant_id_nonempty"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_tenant_topology_configurations_version_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'draft', 'archived')",
            name=op.f("ck_tenant_topology_configurations_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_tenant_topology_configurations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "config_id",
            name=op.f("pk_tenant_topology_configurations"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "topology_name",
            name="uq_tenant_topology_configurations_tenant_name",
        ),
    )
    for col in ("tenant_id", "topology_name", "status"):
        op.create_index(
            op.f(f"ix_tenant_topology_configurations_{col}"),
            "tenant_topology_configurations",
            [col],
        )
    op.create_index(
        "ix_tenant_topology_configurations_tenant_status",
        "tenant_topology_configurations",
        ["tenant_id", "status"],
    )
    op.create_index(
        "uq_tenant_topology_configurations_active_tenant",
        "tenant_topology_configurations",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_table("tenant_topology_configurations")
