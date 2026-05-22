"""Phase 2-D governance decision -> operational event projection bridge.

This adapter is deliberately outside ``GovernanceRuntime`` and
``OperationalEventRuntime``. Governance persistence remains the
canonical authority for governance decisions; event fabric receives an
inspectable chronology projection and never becomes a policy engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.governance.persistence import (
    BaseGovernanceRepository,
    DecisionQuery,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
)


_GOVERNANCE_PROJECTION_NAMESPACE = uuid.UUID(
    "5b67f9a6-2f8c-4d2f-8ddf-c4bcb0f5e830"
)


class GovernanceEventProjectionError(RuntimeError):
    """Raised when persisted governance lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class GovernanceDecisionEventLineage:
    """Canonical chronology position for one governance decision."""

    runtime_instance_id: uuid.UUID
    sequence: int
    root_decision_id: str
    parent_decision_id: str | None = None


@dataclass(frozen=True, slots=True)
class GovernanceOperationalEventProjection:
    """One projected governance decision and its canonical event."""

    source_decision: GovernanceDecisionRecord
    source_trace: GovernanceTraceRecord | None
    operational_event: OperationalEvent


class GovernanceOperationalEventProjector:
    """Projects governance persistence into the canonical event fabric.

    This bridge reads through ``BaseGovernanceRepository`` and writes
    through ``OperationalEventRuntime``. It does not evaluate policy,
    does not enforce decisions, and does not mutate governance records.
    """

    def __init__(
        self,
        *,
        governance_repository: BaseGovernanceRepository,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._governance_repository = governance_repository
        self._event_runtime = event_runtime

    async def project_decision(
        self,
        decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> GovernanceOperationalEventProjection:
        """Project one persisted governance decision."""

        decision = await self._governance_repository.get_decision(
            decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None:
            raise GovernanceEventProjectionError(
                f"unknown governance decision for event projection: {decision_id}"
            )

        trace = await self._governance_repository.get_trace(
            decision.decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        lineage = await self._resolve_lineage_for_decision(
            decision,
            expected_tenant_id=expected_tenant_id,
        )
        event = project_governance_decision_record(
            decision=decision,
            trace=trace,
            lineage=lineage,
        )
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return GovernanceOperationalEventProjection(
            source_decision=decision,
            source_trace=trace,
            operational_event=append.event,
        )

    async def project_correlation_decisions(
        self,
        correlation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[GovernanceOperationalEventProjection, ...]:
        """Project all visible governance decisions for one correlation."""

        decisions = await self._query_all_decisions(
            DecisionQuery(
                correlation_id=correlation_id,
                tenant_id=expected_tenant_id,
            )
        )
        if not decisions:
            return ()

        ordered = _order_decisions(decisions)
        _validate_decision_group_tenant_consistency(ordered)
        projections: list[GovernanceOperationalEventProjection] = []
        for index, decision in enumerate(ordered):
            trace = await self._governance_repository.get_trace(
                decision.decision_id,
                expected_tenant_id=expected_tenant_id,
            )
            lineage = _lineage_from_ordered_decisions(
                ordered,
                index=index,
            )
            event = project_governance_decision_record(
                decision=decision,
                trace=trace,
                lineage=lineage,
            )
            append = await self._event_runtime.append_event(
                event,
                expected_tenant_id=expected_tenant_id,
            )
            projections.append(
                GovernanceOperationalEventProjection(
                    source_decision=decision,
                    source_trace=trace,
                    operational_event=append.event,
                )
            )
        return tuple(projections)

    async def _resolve_lineage_for_decision(
        self,
        decision: GovernanceDecisionRecord,
        *,
        expected_tenant_id: str | None,
    ) -> GovernanceDecisionEventLineage:
        if decision.correlation_id is None:
            return _root_lineage_for_decision(decision)

        decisions = await self._query_all_decisions(
            DecisionQuery(
                correlation_id=decision.correlation_id,
                tenant_id=decision.tenant_id,
            )
        )
        ordered = _order_decisions(decisions)
        _validate_decision_group_tenant_consistency(ordered)
        for index, candidate in enumerate(ordered):
            if candidate.decision_id == decision.decision_id:
                return _lineage_from_ordered_decisions(
                    ordered,
                    index=index,
                )

        if expected_tenant_id is not None:
            raise GovernanceEventProjectionError(
                "tenant-scoped governance correlation did not include "
                f"decision {decision.decision_id!r}"
            )
        raise GovernanceEventProjectionError(
            "governance correlation did not include decision "
            f"{decision.decision_id!r}"
        )

    async def _query_all_decisions(
        self,
        query: DecisionQuery,
    ) -> tuple[GovernanceDecisionRecord, ...]:
        limit = 100
        offset = 0
        records: list[GovernanceDecisionRecord] = []
        while True:
            page = await self._governance_repository.query_decisions(
                DecisionQuery(
                    decision_id=query.decision_id,
                    correlation_id=query.correlation_id,
                    request_id=query.request_id,
                    tenant_id=query.tenant_id,
                    stage=query.stage,
                    policy_chain_id=query.policy_chain_id,
                    subject_kind=query.subject_kind,
                    final_decision=query.final_decision,
                    limit=limit,
                    offset=offset,
                )
            )
            records.extend(page.items)
            offset += len(page.items)
            if len(page.items) < limit:
                break
            if page.total >= 0 and offset >= page.total:
                break
        return tuple(records)


def project_governance_decision_record(
    *,
    decision: GovernanceDecisionRecord,
    trace: GovernanceTraceRecord | None = None,
    lineage: GovernanceDecisionEventLineage | None = None,
) -> OperationalEvent:
    """Convert one persisted governance decision to an OperationalEvent."""

    if trace is not None:
        _validate_trace_matches_decision(decision=decision, trace=trace)
    event_lineage = lineage or _root_lineage_for_decision(decision)
    event_id = EventId(decision.decision_id)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.GOVERNANCE_DECIDE,
        substrate=OperationalSubstrate.GOVERNANCE,
        causality=EventCausality(
            root_event_id=EventId(event_lineage.root_decision_id),
            parent_event_id=(
                EventId(event_lineage.parent_decision_id)
                if event_lineage.parent_decision_id is not None
                else None
            ),
            depth=event_lineage.sequence,
        ),
        chronology=EventChronology(
            runtime_instance_id=event_lineage.runtime_instance_id,
            sequence=event_lineage.sequence,
            occurred_at=_parse_datetime(decision.decided_at),
        ),
        tenant_id=decision.tenant_id,
        principal_id=_metadata_optional(
            "principal_id",
            decision=decision,
            trace=trace,
        ),
        organization_id=_metadata_optional(
            "organization_id",
            decision=decision,
            trace=trace,
        ),
        environment_id=_metadata_optional(
            "environment_id",
            decision=decision,
            trace=trace,
        ),
        tenant_authority_source=(
            _metadata_optional(
                "tenant_authority_source",
                decision=decision,
                trace=trace,
            )
            or _metadata_optional(
                "authority_source",
                decision=decision,
                trace=trace,
            )
        ),
        governance_decision=Decision(decision.decision),
        governance_decision_id=decision.decision_id,
        metadata=_projection_metadata(
            decision=decision,
            trace=trace,
            lineage=event_lineage,
        ),
    )


def _validate_trace_matches_decision(
    *,
    decision: GovernanceDecisionRecord,
    trace: GovernanceTraceRecord,
) -> None:
    mismatches: list[str] = []
    if trace.decision_id != decision.decision_id:
        mismatches.append("decision_id")
    if trace.final_decision != decision.decision:
        mismatches.append("decision/final_decision")
    if trace.stage != decision.stage:
        mismatches.append("stage")
    if trace.policy_chain_id != decision.policy_chain_id:
        mismatches.append("policy_chain_id")
    if trace.tenant_id != decision.tenant_id:
        mismatches.append("tenant_id")
    if trace.request_id != decision.request_id:
        mismatches.append("request_id")
    if trace.correlation_id != decision.correlation_id:
        mismatches.append("correlation_id")
    if mismatches:
        raise GovernanceEventProjectionError(
            "governance trace does not match decision record: "
            + ", ".join(mismatches)
        )


def _root_lineage_for_decision(
    decision: GovernanceDecisionRecord,
) -> GovernanceDecisionEventLineage:
    return GovernanceDecisionEventLineage(
        runtime_instance_id=_uuid_from_stable_text(
            decision.decision_id,
            prefix="governance-decision",
        ),
        sequence=0,
        root_decision_id=decision.decision_id,
    )


def _lineage_from_ordered_decisions(
    decisions: tuple[GovernanceDecisionRecord, ...],
    *,
    index: int,
) -> GovernanceDecisionEventLineage:
    if not decisions:
        raise GovernanceEventProjectionError(
            "governance decision lineage requires at least one decision"
        )
    decision = decisions[index]
    root = decisions[0]
    parent = decisions[index - 1] if index > 0 else None
    correlation_id = decision.correlation_id
    if correlation_id is None:
        return _root_lineage_for_decision(decision)
    return GovernanceDecisionEventLineage(
        runtime_instance_id=_uuid_from_stable_text(
            correlation_id,
            prefix="governance-correlation",
        ),
        sequence=index,
        root_decision_id=root.decision_id,
        parent_decision_id=parent.decision_id if parent is not None else None,
    )


def _order_decisions(
    decisions: tuple[GovernanceDecisionRecord, ...],
) -> tuple[GovernanceDecisionRecord, ...]:
    return tuple(
        sorted(
            decisions,
            key=lambda record: (
                _parse_datetime(record.decided_at),
                record.decision_id,
            ),
        )
    )


def _validate_decision_group_tenant_consistency(
    decisions: tuple[GovernanceDecisionRecord, ...],
) -> None:
    tenant_ids = {decision.tenant_id for decision in decisions}
    if len(tenant_ids) > 1:
        raise GovernanceEventProjectionError(
            "governance correlation contains multiple tenant scopes; "
            "refusing to project a cross-tenant chronology lane"
        )


def _projection_metadata(
    *,
    decision: GovernanceDecisionRecord,
    trace: GovernanceTraceRecord | None,
    lineage: GovernanceDecisionEventLineage,
) -> Mapping[str, Any]:
    return {
        "projection_source": "governance_decision",
        "source_decision_id": decision.decision_id,
        "source_trace_present": trace is not None,
        "source_stage": decision.stage,
        "source_policy_chain_id": decision.policy_chain_id,
        "source_governance_version": decision.governance_version,
        "source_correlation_id": decision.correlation_id,
        "source_request_id": decision.request_id,
        "source_subject_kind": decision.subject_kind,
        "source_decision": decision.decision,
        "source_decided_at": decision.decided_at,
        "governance_lineage": {
            "runtime_instance_id": str(lineage.runtime_instance_id),
            "sequence": lineage.sequence,
            "root_decision_id": lineage.root_decision_id,
            "parent_decision_id": lineage.parent_decision_id,
        },
        "source_decision_record": decision.to_dict(),
        "source_trace_record": trace.to_dict() if trace is not None else None,
    }


def _metadata_optional(
    key: str,
    *,
    decision: GovernanceDecisionRecord,
    trace: GovernanceTraceRecord | None,
) -> str | None:
    value = None
    if trace is not None:
        value = trace.metadata.get(key)
    if value is None:
        value = decision.metadata.get(key)
    if value is None:
        return None
    text = str(value)
    return text or None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _uuid_from_stable_text(value: str, *, prefix: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid5(_GOVERNANCE_PROJECTION_NAMESPACE, f"{prefix}:{value}")


__all__ = [
    "GovernanceDecisionEventLineage",
    "GovernanceEventProjectionError",
    "GovernanceOperationalEventProjection",
    "GovernanceOperationalEventProjector",
    "project_governance_decision_record",
]
