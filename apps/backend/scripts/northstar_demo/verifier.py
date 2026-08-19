"""Strict, read-only verifier for the immutable Northstar fixture.

This module deliberately owns classification, not repair.  Its public result
contains only stable enum values, allowlisted reason codes, and aggregate
counts so the operator CLI cannot become a tenant-data disclosure surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.db.models import OperationalEventRow
from app.governance.db.models import GovernanceDecisionRow, GovernanceTraceRow
from app.qa.db.models import QAScoreRow
from app.resolution.db.models import ResolutionProposalRow
from app.session.db.models import SessionEventRow, SessionRow
from app.supervisor.db.models import SupervisorInspectionRow
from app.tenant.db.models import (
    ConnectorConfigRow,
    ConnectorCredentialRow,
    TenantChannelConfigurationRow,
    TenantExecutionCircuitBreakerRow,
    TenantExecutionGovernanceConfigurationRow,
    TenantRow,
    TenantTopologyConfigurationRow,
)

from .manifest import NorthstarDemoManifest, SEEDED_SESSION_SEQUENCE_HEAD


class NorthstarVerificationClassification(StrEnum):
    ABSENT = "ABSENT"
    COMPLETE_MATCH = "COMPLETE_MATCH"
    UNSAFE_PARTIAL_OR_MISMATCH = "UNSAFE_PARTIAL_OR_MISMATCH"


@dataclass(frozen=True, slots=True)
class NorthstarVerificationResult:
    """Sanitized verifier outcome; never include stored values in this type."""

    classification: NorthstarVerificationClassification
    reason_codes: tuple[str, ...]
    expected_counts: tuple[tuple[str, int], ...]
    forbidden_counts: tuple[tuple[str, int], ...]


_EXPECTED_COUNTS: Final[tuple[tuple[str, int], ...]] = (
    ("tenant", 1),
    ("tenant_lifecycle_event", 1),
    ("session", 1),
    ("session_event", 3),
    ("governance_decision", 1),
    ("governance_trace", 1),
    ("resolution_proposal", 1),
    ("action_approval", 1),
    ("supervisor_inspection", 1),
    ("qa_score", 1),
)


async def verify_northstar_fixture(
    session: AsyncSession,
    *,
    manifest: NorthstarDemoManifest,
) -> NorthstarVerificationResult:
    """Classify the fixed fixture without changing application state.

    Callers own transaction policy.  This function makes no transaction,
    flush, task, network, or provider call and treats any query failure as an
    unsafe result rather than an absence claim.
    """

    try:
        with session.no_autoflush:
            return await _verify(session, manifest=manifest)
    except Exception:  # noqa: BLE001 - verification must fail closed
        return _unsafe("repository_error")


async def verify_northstar_fixture_read_only(
    session: AsyncSession,
    *,
    manifest: NorthstarDemoManifest,
) -> NorthstarVerificationResult:
    """Run the shared core in a transaction explicitly marked read-only."""

    if session.in_transaction():
        return _unsafe("read_only_transaction_required")
    try:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(
            text("SELECT set_config('app.platform_tenant_admin', 'true', true)")
        )
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": manifest.tenant_id},
        )
        return await verify_northstar_fixture(session, manifest=manifest)
    finally:
        await session.rollback()


async def _verify(
    session: AsyncSession, *, manifest: NorthstarDemoManifest
) -> NorthstarVerificationResult:
    tenant = await session.get(TenantRow, manifest.tenant_id)
    collisions = await _deterministic_collision_count(session, manifest=manifest)
    if tenant is None:
        if collisions == 0:
            return NorthstarVerificationResult(
                NorthstarVerificationClassification.ABSENT,
                (),
                _EXPECTED_COUNTS,
                await _forbidden_counts(session, manifest=manifest),
            )
        return _unsafe("deterministic_collision")

    reasons: set[str] = set()
    if tenant.status != "active":
        reasons.add("tenant_status_mismatch")

    lifecycle_count = await _count(
        session,
        select(OperationalEventRow).where(
            OperationalEventRow.tenant_id == manifest.tenant_id,
            OperationalEventRow.operational_act == "hardening:tenant_create",
            OperationalEventRow.metadata_json["projection_source"].astext
            == "tenant_lifecycle",
        ),
    )
    if lifecycle_count != 1:
        reasons.add("tenant_lifecycle_event_mismatch")

    expected_singletons = (
        ("session", SessionRow, SessionRow.tenant_id),
        ("governance_decision", GovernanceDecisionRow, GovernanceDecisionRow.tenant_id),
        ("governance_trace", GovernanceTraceRow, GovernanceTraceRow.tenant_id),
        ("resolution_proposal", ResolutionProposalRow, ResolutionProposalRow.tenant_id),
        ("supervisor_inspection", SupervisorInspectionRow, SupervisorInspectionRow.tenant_id),
        ("qa_score", QAScoreRow, QAScoreRow.tenant_id),
    )
    for label, model, tenant_column in expected_singletons:
        if await _count(session, select(model).where(tenant_column == manifest.tenant_id)) != 1:
            reasons.add(f"{label}_count_mismatch")
    approval_count = int(
        (
            await session.execute(
                text("SELECT count(*) FROM action_approval_records WHERE tenant_id = :tenant_id"),
                {"tenant_id": manifest.tenant_id},
            )
        ).scalar_one()
    )
    if approval_count != 1:
        reasons.add("action_approval_count_mismatch")

    session_row = await session.get(SessionRow, manifest.session_id)
    if session_row is None:
        reasons.add("session_missing")
    elif not _valid_session(session_row, manifest=manifest):
        reasons.add("session_mismatch")

    events = (
        await session.execute(
            select(SessionEventRow)
            .where(SessionEventRow.session_id == manifest.session_id)
            .order_by(SessionEventRow.sequence)
        )
    ).scalars().all()
    if not _valid_events(events, manifest=manifest):
        reasons.add("session_timeline_mismatch")

    decision = await session.get(GovernanceDecisionRow, manifest.governance_decision_id)
    trace = await session.get(GovernanceTraceRow, manifest.governance_decision_id)
    if not _valid_governance(decision, trace, manifest=manifest):
        reasons.add("governance_mismatch")

    proposal = await session.get(ResolutionProposalRow, manifest.proposal_id)
    if not _valid_proposal(proposal, manifest=manifest):
        reasons.add("proposal_mismatch")

    approval = await _approval_row(session, manifest=manifest)
    if not _valid_approval(approval, manifest=manifest):
        reasons.add("approval_mismatch")

    inspection = await session.get(SupervisorInspectionRow, manifest.inspection_id)
    qa_score = await session.get(QAScoreRow, manifest.qa_score_id)
    if not _valid_inspection(inspection, manifest=manifest):
        reasons.add("inspection_mismatch")
    if not _valid_qa_score(qa_score, manifest=manifest):
        reasons.add("qa_score_mismatch")

    forbidden = await _forbidden_counts(session, manifest=manifest)
    if any(count for _, count in forbidden):
        reasons.add("forbidden_resource_present")
    if reasons:
        return NorthstarVerificationResult(
            NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH,
            tuple(sorted(reasons)),
            _EXPECTED_COUNTS,
            forbidden,
        )
    return NorthstarVerificationResult(
        NorthstarVerificationClassification.COMPLETE_MATCH,
        (),
        _EXPECTED_COUNTS,
        forbidden,
    )


async def _deterministic_collision_count(
    session: AsyncSession, *, manifest: NorthstarDemoManifest
) -> int:
    """Detect target IDs outside an absent target tenant without broad reads."""

    statements = (
        select(func.count()).select_from(SessionRow).where(SessionRow.session_id == manifest.session_id),
        select(func.count()).select_from(ResolutionProposalRow).where(ResolutionProposalRow.proposal_id == manifest.proposal_id),
        select(func.count()).select_from(GovernanceDecisionRow).where(GovernanceDecisionRow.decision_id == manifest.governance_decision_id),
        select(func.count()).select_from(SupervisorInspectionRow).where(SupervisorInspectionRow.inspection_id == manifest.inspection_id),
        select(func.count()).select_from(QAScoreRow).where(QAScoreRow.score_id == manifest.qa_score_id),
        text("SELECT count(*) FROM action_approval_records WHERE approval_id = :approval_id"),
    )
    total = 0
    for stmt in statements:
        params = {"approval_id": str(manifest.approval_id)} if isinstance(stmt, type(text("SELECT 1"))) else {}
        total += int((await session.execute(stmt, params)).scalar_one())
    return total


async def _forbidden_counts(
    session: AsyncSession, *, manifest: NorthstarDemoManifest
) -> tuple[tuple[str, int], ...]:
    direct_models = (
        ("connector_configurations", ConnectorConfigRow),
        ("connector_credentials", ConnectorCredentialRow),
        ("channel_configurations", TenantChannelConfigurationRow),
        ("action_executor_configuration", TenantExecutionGovernanceConfigurationRow),
        ("action_tool_topology", TenantTopologyConfigurationRow),
        ("execution_circuit_breakers", TenantExecutionCircuitBreakerRow),
    )
    counts: list[tuple[str, int]] = []
    for label, model in direct_models:
        counts.append((label, await _count(session, select(model).where(model.tenant_id == manifest.tenant_id))))
    raw_target_tables = (
        ("resolution_outbound_drafts", "resolution_outbound_drafts"),
        ("outbound_send_outbox", "outbound_send_outbox"),
        ("ingress_dispatch_outbox", "ingress_dispatch_outbox"),
        ("connector_invocations", "connector_invocations"),
        ("execution_records", "execution_records"),
        ("execution_outbox", "execution_outbox"),
        ("dead_letter_tasks", "dead_letter_tasks"),
        ("escalation_outbox", "escalation_outbox"),
        ("outbound_dispatch_records", "outbound_dispatch_records"),
        ("work_order_records", "work_order_records"),
        ("email_customer_reply_deliveries", "email_customer_reply_deliveries"),
        ("whatsapp_customer_reply_deliveries", "whatsapp_customer_reply_deliveries"),
        ("whatsapp_media_fetch_records", "whatsapp_media_fetch_records"),
        ("webhook_nonce_records", "webhook_nonce_records"),
    )
    for label, table in raw_target_tables:
        exists = (await session.execute(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": f"public.{table}"})).scalar_one()
        if not exists:
            counts.append((label, 0))
            continue
        has_tenant = (await session.execute(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=:table AND column_name='tenant_id')"), {"table": table})).scalar_one()
        if not has_tenant:
            counts.append((label, 0))
            continue
        counts.append((label, int((await session.execute(text(f"SELECT count(*) FROM public.{table} WHERE tenant_id = :tenant_id"), {"tenant_id": manifest.tenant_id})).scalar_one())))
    return tuple(counts)


async def _count(session: AsyncSession, statement: Any) -> int:
    result = await session.execute(statement)
    return len(result.all())


async def _approval_row(
    session: AsyncSession, *, manifest: NorthstarDemoManifest
) -> Mapping[str, Any] | None:
    row = (
        await session.execute(
            text("SELECT approval_id, tenant_id, session_id, execution_id, tool_name, idempotency_key, governance_decision_id, status, resolved_at, resolved_by FROM action_approval_records WHERE approval_id = :approval_id"),
            {"approval_id": str(manifest.approval_id)},
        )
    ).mappings().one_or_none()
    return cast(Mapping[str, Any] | None, row)


def _valid_session(row: SessionRow, *, manifest: NorthstarDemoManifest) -> bool:
    return row.tenant_id == manifest.tenant_id and row.scope == "tenant" and row.external_handle == "northstar-clueso-demo-maya-chen" and row.lifecycle_phase == "dormant" and row.sequence_head == SEEDED_SESSION_SEQUENCE_HEAD and row.opened_at == manifest.opened_at and row.lifecycle_recorded_at == manifest.inspection_at


def _valid_events(rows: Sequence[SessionEventRow], *, manifest: NorthstarDemoManifest) -> bool:
    if len(rows) != 3:
        return False
    expected = ((0, "session_opened", None), (1, "customer_message", None), (2, "operational_observation", "resolution_proposal_created"))
    for row, (sequence, kind, annotation) in zip(rows, expected, strict=True):
        if row.event_id != manifest.session_id and row.event_id != _event_id(manifest, sequence):
            return False
        if row.sequence != sequence or row.kind != kind or row.annotation != annotation or row.session_id != manifest.session_id:
            return False
    proposal = rows[2].payload
    inner = proposal.get("payload")
    if not isinstance(inner, dict):
        return False
    inner_payload = cast(dict[str, Any], inner)
    return proposal.get("tenant_id") == manifest.tenant_id and proposal.get("session_id") == str(manifest.session_id) and proposal.get("event_type") == "resolution_proposal_created" and inner_payload.get("proposal_id") == str(manifest.proposal_id) and inner_payload.get("status") == "pending_human_approval" and inner_payload.get("recommended_actions") == [{"type": "replacement.order", "label": "Review proposed replacement", "requires_execution": True}]


def _event_id(manifest: NorthstarDemoManifest, sequence: int):
    from .manifest import stable_id
    return stable_id(f"session-event-{sequence}")


def _valid_governance(decision: GovernanceDecisionRow | None, trace: GovernanceTraceRow | None, *, manifest: NorthstarDemoManifest) -> bool:
    return decision is not None and trace is not None and decision.tenant_id == manifest.tenant_id and decision.decision == "require_approval" and decision.stage == "resolution_governance_gate" and trace.tenant_id == manifest.tenant_id and trace.decision_id == manifest.governance_decision_id and trace.final_decision == "require_approval" and trace.action == "replacement.order" and trace.request_id == str(manifest.session_id)


def _valid_proposal(row: ResolutionProposalRow | None, *, manifest: NorthstarDemoManifest) -> bool:
    return row is not None and row.tenant_id == manifest.tenant_id and row.session_id == manifest.session_id and row.status == "pending_human_approval" and row.governance_decision_id == manifest.governance_decision_id and row.resolution_category == "synthetic_demo" and row.execution_id is None and row.recommended_actions == [{"type": "replacement.order", "label": "Review proposed replacement", "requires_execution": True}]


def _valid_approval(row: Mapping[str, Any] | None, *, manifest: NorthstarDemoManifest) -> bool:
    if row is None:
        return False
    return row["tenant_id"] == manifest.tenant_id and str(row["session_id"]) == str(manifest.session_id) and row["tool_name"] == "replacement.order" and row["status"] == "pending" and row["execution_id"] is None and row["resolved_at"] is None and row["resolved_by"] is None and str(row["governance_decision_id"]) == str(manifest.governance_decision_id) and str(row["idempotency_key"]) == str(manifest.approval_idempotency_key)


def _valid_inspection(row: SupervisorInspectionRow | None, *, manifest: NorthstarDemoManifest) -> bool:
    return row is not None and row.tenant_id == manifest.tenant_id and row.execution_id == manifest.execution_id and row.correlation_id == str(manifest.session_id) and row.request_id == str(manifest.session_id) and row.decision_kind == "needs_human_review" and row.inspection_mode == "synthetic_demo"


def _valid_qa_score(row: QAScoreRow | None, *, manifest: NorthstarDemoManifest) -> bool:
    return row is not None and row.tenant_id == manifest.tenant_id and row.inspection_id == manifest.inspection_id and row.execution_id == manifest.execution_id and row.supervisor_decision_kind == "needs_human_review" and row.overall_score == 1.0


def _unsafe(*reason_codes: str) -> NorthstarVerificationResult:
    return NorthstarVerificationResult(NorthstarVerificationClassification.UNSAFE_PARTIAL_OR_MISMATCH, tuple(sorted(set(reason_codes))), _EXPECTED_COUNTS, ())
