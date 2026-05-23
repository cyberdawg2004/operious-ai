"""multi-tenant production hardening (Phase 6-D)

Revision ID: 0025_multi_tenant_hardening
Revises: 0024_execution_governance
Create Date: 2026-05-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_multi_tenant_hardening"
down_revision: Union[str, None] = "0024_execution_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_PARTITION_STRATEGY_COMMENT = (
    "Phase 6-D tenant hardening: row-level security is enabled; "
    "high-volume non-null tenant tables follow the LIST (tenant_id) "
    "promotion strategy in app.db.partitioning, starting with a DEFAULT "
    "partition and attaching dedicated tenant partitions as volume proves it."
)

TENANT_RLS_DIRECT_TABLES: tuple[str, ...] = (
    "tenants",
    "governance_decisions",
    "governance_traces",
    "operational_sessions",
    "coordination_envelopes",
    "arbitration_evaluations",
    "supervisor_inspections",
    "boundary_ingress",
    "boundary_egress",
    "execution_records",
    "operational_events",
    "tenant_channel_configurations",
    "tenant_knowledge_documents",
    "tenant_knowledge_document_versions",
    "tenant_governance_policies",
    "tenant_topology_configurations",
    "tenant_knowledge_chunks",
    "tenant_knowledge_vectors",
    "qa_score_records",
    "escalation_records",
    "approval_records",
    "cognition_llm_usage_records",
    "operational_slo_definitions",
    "operational_trace_spans",
    "tenant_execution_governance_configurations",
    "tenant_execution_circuit_breakers",
)

TENANT_RLS_PARENT_TABLES: tuple[tuple[str, str, str, str], ...] = (
    (
        "governance_enforcement_actions",
        "decision_id",
        "governance_decisions",
        "decision_id",
    ),
    ("session_events", "session_id", "operational_sessions", "session_id"),
    (
        "session_correlations",
        "session_id",
        "operational_sessions",
        "session_id",
    ),
    ("execution_attempts", "execution_id", "execution_records", "execution_id"),
    ("execution_outbox", "execution_id", "execution_records", "execution_id"),
    (
        "supervisor_findings",
        "inspection_id",
        "supervisor_inspections",
        "inspection_id",
    ),
    (
        "supervisor_evaluations",
        "inspection_id",
        "supervisor_inspections",
        "inspection_id",
    ),
    (
        "supervisor_escalations",
        "inspection_id",
        "supervisor_inspections",
        "inspection_id",
    ),
)


def upgrade() -> None:
    op.add_column(
        "tenant_channel_configurations",
        sa.Column("previous_credentials_enc", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "tenant_channel_configurations",
        sa.Column("previous_webhook_secret", sa.Text(), nullable=True),
    )
    op.add_column(
        "tenant_channel_configurations",
        sa.Column("credential_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenant_channel_configurations",
        sa.Column(
            "credential_rotation_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    _create_rls_helper()
    _enable_direct_rls()
    _enable_parent_rls()
    _apply_partition_strategy_comments()


def downgrade() -> None:
    for table, *_ in reversed(TENANT_RLS_PARENT_TABLES):
        _drop_policy(table)
        op.execute(f"ALTER TABLE {_q(table)} DISABLE ROW LEVEL SECURITY")
    for table in reversed(TENANT_RLS_DIRECT_TABLES):
        _drop_policy(table)
        op.execute(f"ALTER TABLE {_q(table)} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS operious_tenant_rls_allows(text)")
    op.drop_column(
        "tenant_channel_configurations",
        "credential_rotation_expires_at",
    )
    op.drop_column("tenant_channel_configurations", "credential_rotated_at")
    op.drop_column("tenant_channel_configurations", "previous_webhook_secret")
    op.drop_column("tenant_channel_configurations", "previous_credentials_enc")


def _create_rls_helper() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION operious_tenant_rls_allows(row_tenant_id text)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT row_tenant_id IS NULL
                OR row_tenant_id = current_setting('app.current_tenant_id', true)
        $$;
        """
    )


def _enable_direct_rls() -> None:
    for table in TENANT_RLS_DIRECT_TABLES:
        _drop_policy(table)
        op.execute(f"ALTER TABLE {_q(table)} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {_q(table)}
            USING (operious_tenant_rls_allows(tenant_id))
            WITH CHECK (operious_tenant_rls_allows(tenant_id))
            """
        )


def _enable_parent_rls() -> None:
    for table, local_column, parent_table, parent_column in TENANT_RLS_PARENT_TABLES:
        _drop_policy(table)
        op.execute(f"ALTER TABLE {_q(table)} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {_q(table)}
            USING (
                EXISTS (
                    SELECT 1
                    FROM {_q(parent_table)} AS parent_scope
                    WHERE parent_scope.{_q(parent_column)}
                        = {_q(table)}.{_q(local_column)}
                    AND operious_tenant_rls_allows(parent_scope.tenant_id)
                )
            )
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM {_q(parent_table)} AS parent_scope
                    WHERE parent_scope.{_q(parent_column)}
                        = {_q(table)}.{_q(local_column)}
                    AND operious_tenant_rls_allows(parent_scope.tenant_id)
                )
            )
            """
        )


def _apply_partition_strategy_comments() -> None:
    escaped = TENANT_PARTITION_STRATEGY_COMMENT.replace("'", "''")
    for table in (*TENANT_RLS_DIRECT_TABLES, *(t[0] for t in TENANT_RLS_PARENT_TABLES)):
        op.execute(f"COMMENT ON TABLE {_q(table)} IS '{escaped}'")


def _drop_policy(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_q(table)}")


def _q(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
