"""Enable Row Level Security on connector_credentials table.

Revision ID: 0104_connector_credentials_rls
Revises: 0103_backfill_action_approval_proposed_by_sentinel
Create Date: 2026-07-07

Security fix: migration 0100 created ``connector_credentials`` without RLS,
leaving a defence-in-depth gap where any PostgreSQL role not constrained by
application-level tenant filters could read credentials across tenants.

The application service layer already passes ``tenant_id`` in every query
(confirmed in tenant_config_change_request_service.py), but database-layer
enforcement is required for:
  1. Defence-in-depth if application code ever misses a filter.
  2. Protection against direct DB access (ops tooling, migrations, DBA queries).
  3. Consistency with all other tenant-scoped tables (connector_configs,
     action_approval_records, etc.) which all have FORCE RLS.

Adds:
  - ENABLE ROW LEVEL SECURITY
  - tenant_isolation POLICY (matches all other tenant tables)
  - FORCE ROW LEVEL SECURITY (protects table owner too)
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0104_connector_credentials_rls"
down_revision: Union[str, None] = "0103_backfill_action_approval_proposed_by_sentinel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.connector_credentials ENABLE ROW LEVEL SECURITY"
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.connector_credentials
        USING (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            tenant_id = current_setting('app.current_tenant_id', true)
        )
        """
    )
    op.execute(
        "ALTER TABLE public.connector_credentials FORCE ROW LEVEL SECURITY"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.connector_credentials NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.connector_credentials"
    )
    op.execute(
        "ALTER TABLE public.connector_credentials DISABLE ROW LEVEL SECURITY"
    )
