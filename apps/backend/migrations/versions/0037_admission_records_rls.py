"""force row level security for admission records

Revision ID: 0037_admission_records_rls
Revises: 0036_admission_records
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0037_admission_records_rls"
down_revision: Union[str, None] = "0036_admission_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.admission_records ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON public.admission_records
        USING (operious_tenant_rls_allows(tenant_id))
        WITH CHECK (operious_tenant_rls_allows(tenant_id))
        """
    )
    op.execute("ALTER TABLE public.admission_records FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.admission_records NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON public.admission_records"
    )
    op.execute("ALTER TABLE public.admission_records DISABLE ROW LEVEL SECURITY")
