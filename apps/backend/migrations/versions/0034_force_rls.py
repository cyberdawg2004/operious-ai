"""force tenant row level security

Revision ID: 0034_force_rls
Revises: 0033_rls_routing_resolver
Create Date: 2026-05-25 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

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


def upgrade() -> None:
    for table_name in _FORCED_RLS_TABLES:
        op.execute(f'ALTER TABLE public."{table_name}" FORCE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table_name in reversed(_FORCED_RLS_TABLES):
        op.execute(f'ALTER TABLE public."{table_name}" NO FORCE ROW LEVEL SECURITY')
