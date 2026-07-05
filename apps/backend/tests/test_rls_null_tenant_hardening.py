"""Static test: RLS tenant-id NOT NULL hardening invariant.

Asserts that every table that has FORCE ROW LEVEL SECURITY enabled in the
migration history has a ``tenant_id`` column that is ``nullable=False`` on
the ORM model.  This is a defence-in-depth check: the NULL branch in

    operious_tenant_rls_allows(row_tenant_id) :=
        row_tenant_id IS NULL
        OR row_tenant_id = current_setting('app.current_tenant_id', true)

means a NULL tenant_id is visible to *every* tenant context.  If the
column is NOT NULL at the schema layer, no row can ever be NULL and that
branch is dead, eliminating the gap.

This is a STATIC test — no database connection is required.  It imports the
ORM model classes and inspects the Column objects directly.

Tables covered
--------------
From migration 0025 (TENANT_RLS_DIRECT_TABLES):
  tenants, governance_decisions, governance_traces, operational_sessions,
  coordination_envelopes, arbitration_evaluations, supervisor_inspections,
  boundary_ingress, boundary_egress, execution_records,
  operational_events, tenant_channel_configurations,
  tenant_knowledge_documents, tenant_knowledge_document_versions,
  tenant_governance_policies, tenant_topology_configurations,
  tenant_knowledge_chunks, tenant_knowledge_vectors, qa_score_records,
  escalation_records, approval_records, cognition_llm_usage_records,
  operational_slo_definitions, operational_trace_spans,
  tenant_execution_governance_configurations, tenant_execution_circuit_breakers

From migration 0087 (FORCE RLS added):
  connector_configs

Parent-table RLS (tenant scope comes from join to parent; no direct
tenant_id on these tables — they are excluded):
  governance_enforcement_actions, session_events, session_correlations,
  execution_attempts, execution_outbox, supervisor_findings,
  supervisor_evaluations, supervisor_escalations

System/cross-tenant tables excluded from this invariant:
  None — governance_decisions was previously nullable by doctrine but the
  ORM has already been tightened to nullable=False (see GovernanceDecisionRow).
"""

from __future__ import annotations

import sys
import os
import importlib
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Ensure the app package is importable
# ---------------------------------------------------------------------------

_BACKEND_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "app", "..")
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# ---------------------------------------------------------------------------
# Tables with FORCE RLS that must have nullable=False tenant_id
# ---------------------------------------------------------------------------

# Direct tables from migration 0025 that have their own tenant_id column
# (parent-table entries from TENANT_RLS_PARENT_TABLES are excluded because
# they do not have a tenant_id column at all — they inherit scope via join).
FORCE_RLS_DIRECT_TABLES_WITH_TENANT_ID: tuple[str, ...] = (
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
    # From migration 0087
    "connector_configs",
)

# ---------------------------------------------------------------------------
# Helper: collect all ORM models registered against the shared metadata
# ---------------------------------------------------------------------------

def _load_all_models() -> None:
    """Import every db/models module so all ORM classes register with Base."""
    model_modules = [
        "app.boundary.db.models",
        "app.session.db.models",
        "app.execution.db.models",
        "app.tenant.db.models",
        "app.governance.db.models",
        "app.knowledge.db.models",
        "app.coordination.db.models",
        "app.arbitration.db.models",
        "app.supervisor.db.models",
        "app.events.db.models",
        "app.escalation.db.models",
        "app.approvals.db.models",
        "app.qa.db.models",
        "app.cognition.db.models",
        "app.observability.db.models",
        "app.resolution.db.models",
        "app.runtime.db.models",
        "app.semantic.db.models",
        "app.sop_intelligence.db.models",
        "app.trainer.db.models",
        "app.work_orders.db.models",
        "app.attachments.db.models",
        "app.data_protection.db.models",
    ]
    for module_path in model_modules:
        try:
            importlib.import_module(module_path)
        except ImportError:
            pass  # optional / not yet present modules are skipped


def _get_table_to_model_map() -> dict[str, Any]:
    """Return {tablename: mapper} for all registered ORM models."""
    from app.db.base import Base  # noqa: PLC0415

    _load_all_models()
    result: dict[str, Any] = {}
    for mapper in Base.registry.mappers:
        tablename = mapper.persist_selectable.name
        result[tablename] = mapper
    return result


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

def _get_tenant_id_nullable(mapper: Any) -> bool | None:
    """Return the nullable setting for tenant_id on the mapped table.

    Returns None if the column does not exist on the table.
    """
    table = mapper.persist_selectable
    col = table.c.get("tenant_id")
    if col is None:
        return None
    return col.nullable


@pytest.mark.parametrize("table_name", FORCE_RLS_DIRECT_TABLES_WITH_TENANT_ID)
def test_rls_tenant_id_not_nullable(table_name: str) -> None:
    """tenant_id must be NOT NULL on FORCE RLS tables.

    A nullable tenant_id on a FORCE RLS table means NULL rows are
    visible to every tenant context via the IS NULL branch in the RLS
    policy helper — that is a defence-in-depth gap.
    """
    table_to_mapper = _get_table_to_model_map()

    if table_name not in table_to_mapper:
        pytest.skip(
            f"Table '{table_name}' has no registered ORM model — "
            "ensure the model module is imported above."
        )

    mapper = table_to_mapper[table_name]
    nullable = _get_tenant_id_nullable(mapper)

    if nullable is None:
        # tenants table uses tenant_id as PK — PKs are implicitly NOT NULL.
        # Other parent-table-only RLS entries (governance_enforcement_actions
        # etc.) have no tenant_id — they're excluded from the parametrize list.
        # If we reach here for an unexpected table, fail loudly.
        table = mapper.persist_selectable
        pk_cols = [c.name for c in table.primary_key.columns]
        if "tenant_id" in pk_cols:
            return  # PK is implicitly NOT NULL — invariant holds
        pytest.fail(
            f"Table '{table_name}' has no tenant_id column but is listed in "
            "FORCE_RLS_DIRECT_TABLES_WITH_TENANT_ID."
        )

    assert nullable is False, (
        f"VIOLATION: table '{table_name}' has tenant_id nullable=True "
        f"but is protected by FORCE ROW LEVEL SECURITY. "
        f"A NULL tenant_id row would be visible to every tenant context. "
        f"Add a NOT NULL constraint via migration 0099_harden_rls_tenant_not_null.py."
    )
