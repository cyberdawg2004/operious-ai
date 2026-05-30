"""force tenant row level security

Revision ID: 0034_force_rls
Revises: 0033_rls_routing_resolver
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0034_force_rls"
down_revision: Union[str, None] = "0033_rls_routing_resolver"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FORCED_RLS_TABLES = (
    "approval_records",
    "arbitration_evaluations",
    "boundary_egress",
    "boundary_ingress",
    "cognition_audit_records",
    "cognition_llm_usage_records",
    "coordination_envelopes",
    "dead_letter_tasks",
    "escalation_outbox",
    "escalation_records",
    "execution_attempts",
    "execution_outbox",
    "execution_records",
    "governance_decisions",
    "governance_enforcement_actions",
    "governance_traces",
    "operational_events",
    "operational_sessions",
    "operational_slo_definitions",
    "operational_trace_spans",
    "qa_score_records",
    "session_correlations",
    "session_events",
    "supervisor_escalations",
    "supervisor_evaluations",
    "supervisor_findings",
    "supervisor_inspections",
    "tenant_channel_configurations",
    "tenant_execution_circuit_breakers",
    "tenant_execution_governance_configurations",
    "tenant_governance_policies",
    "tenant_knowledge_chunks",
    "tenant_knowledge_document_versions",
    "tenant_knowledge_documents",
    "tenant_knowledge_vectors",
    "tenant_topology_configurations",
    "tenants",
    "webhook_nonce_records",
)
# `admission_records` is created later in 0036 and forced in 0037. It must
# not be asserted here because this migration protects only tables that exist
# at revision 0034.


def upgrade() -> None:
    # This migration has already run in production. The fail-loud
    # assertion below protects fresh environments from silently skipping
    # FORCE RLS when an expected tenant-scoped table is missing.
    _assert_forced_rls_tables_exist()
    for table_name in _FORCED_RLS_TABLES:
        _alter_force_rls(table_name, force=True)


def downgrade() -> None:
    for table_name in reversed(_FORCED_RLS_TABLES):
        _alter_force_rls(table_name, force=False)


def _assert_forced_rls_tables_exist() -> None:
    conn = op.get_bind()
    missing: list[str] = []
    for table_name in _FORCED_RLS_TABLES:
        result = conn.execute(
            text("SELECT to_regclass(:qualified_table)"),
            {"qualified_table": f"public.{table_name}"},
        ).scalar()
        if result is None:
            missing.append(table_name)
    if missing:
        missing_tables = ", ".join(repr(table_name) for table_name in missing)
        raise RuntimeError(
            "Migration 0034: expected table(s) "
            f"{missing_tables} do not exist. Cannot apply FORCE RLS."
        )


def _alter_force_rls(table_name: str, *, force: bool) -> None:
    conn = op.get_bind()
    escaped_table = table_name.replace('"', '""')
    command = "FORCE" if force else "NO FORCE"
    conn.execute(
        text(
            f'ALTER TABLE public."{escaped_table}" '
            "ENABLE ROW LEVEL SECURITY"
        )
    )
    conn.execute(
        text(
            f'ALTER TABLE public."{escaped_table}" '
            f"{command} ROW LEVEL SECURITY"
        )
    )
