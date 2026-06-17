"""Enable FORCE ROW LEVEL SECURITY on connector_configs; add credential_update change type.

Revision ID: 0087_connector_configs_force_rls
Revises: 0086_knowledge_uploads_and_ingestion_status
Create Date: 2026-06-17

Changes:
  1. connector_configs: add FORCE ROW LEVEL SECURITY (security gap — was
     omitted from the migration-0034 sweep).
  2. tenant_config_change_requests.change_type: extend the check constraint to
     include 'credential_update' (new dual-control OMS credential lifecycle type).

Zero-downtime: the FORCE RLS alter and constraint drop+recreate each obtain a
brief ACCESS EXCLUSIVE lock, but both operations complete in sub-millisecond on
the current table sizes.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0087_connector_configs_force_rls"
down_revision: Union[str, None] = "0086_knowledge_uploads_and_ingestion_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "ck_tenant_config_change_requests_change_type_valid"
_TABLE = "tenant_config_change_requests"
_TYPES_V1 = (
    "knowledge",
    "policy",
    "execution_governance",
    "topology",
    "channel",
    "connector",
)
_TYPES_V2 = _TYPES_V1 + ("credential_update",)


def _in_clause(values: tuple[str, ...]) -> str:
    return "change_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    # 1. FORCE RLS on connector_configs
    op.execute("ALTER TABLE connector_configs FORCE ROW LEVEL SECURITY")

    # 2. Expand change_type allowlist to include credential_update
    op.execute(
        f"ALTER TABLE {_TABLE} "
        f"DROP CONSTRAINT {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} "
        f"ADD CONSTRAINT {_CONSTRAINT} CHECK ({_in_clause(_TYPES_V2)})"
    )


def downgrade() -> None:
    # Revert change_type constraint (remove credential_update)
    op.execute(
        f"ALTER TABLE {_TABLE} "
        f"DROP CONSTRAINT {_CONSTRAINT}"
    )
    op.execute(
        f"ALTER TABLE {_TABLE} "
        f"ADD CONSTRAINT {_CONSTRAINT} CHECK ({_in_clause(_TYPES_V1)})"
    )

    # Revert FORCE RLS on connector_configs
    op.execute("ALTER TABLE connector_configs NO FORCE ROW LEVEL SECURITY")
