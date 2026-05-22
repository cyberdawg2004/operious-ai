"""Phase 2-I arbitration evaluation -> operational event projection bridge.

ArbitrationRuntime remains the canonical authority for arbitration
evaluations. This adapter reads persisted arbitration records and
writes an inspectable chronology projection through
OperationalEventRuntime. It never evaluates conflicts, mutates
arbitration records, dispatches work, or grants arbitration execution
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping
import uuid

from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationEvaluationId,
    as_case_id,
    as_evaluation_id,
)
from app.arbitration.persistence import (
    ArbitrationPersistenceProtocol,
    ArbitrationQuery,
    ArbitrationRecord,
)
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

if TYPE_CHECKING:
    from app.runtime.dispatch_arbitration import DispatchArbitrationRuntime


class ArbitrationEventProjectionError(RuntimeError):
    """Raised when persisted arbitration lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class ArbitrationEvaluationEventLineage:
    """Canonical causality position for one arbitration evaluation."""

    root_evaluation_id: str
    depth: int = 0
    parent_evaluation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ArbitrationOperationalEventProjection:
    """One projected arbitration evaluation and its canonical event."""

    source_record: ArbitrationRecord
    operational_event: OperationalEvent


class ArbitrationOperationalEventProjector:
    """Projects arbitration persistence into canonical event fabric.

    This bridge composes arbitration persistence with
    OperationalEventRuntime. It is a projection boundary only: no
    arbitration evaluation, no governance decisioning, no transport,
    and no source-record mutation happen here.
    """

    def __init__(
        self,
        *,
        arbitration_persistence: ArbitrationPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._arbitration_persistence = arbitration_persistence
        self._event_runtime = event_runtime

    async def project_evaluation(
        self,
        evaluation_id: ArbitrationEvaluationId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> ArbitrationOperationalEventProjection:
        """Project one persisted arbitration evaluation."""

        eid = _coerce_evaluation_id(evaluation_id)
        record = await self._arbitration_persistence.get(
            eid,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise ArbitrationEventProjectionError(
                "unknown arbitration evaluation for event projection: "
                f"{evaluation_id}"
            )
        lineage = await self._resolve_lineage_for_record(
            record,
            expected_tenant_id=expected_tenant_id,
        )
        event = project_arbitration_record(record=record, lineage=lineage)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return ArbitrationOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )

    async def project_case_evaluations(
        self,
        case_id: ArbitrationCaseId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[ArbitrationOperationalEventProjection, ...]:
        """Project all visible evaluations for one arbitration case."""

        records = await self._query_all_records(
            ArbitrationQuery(
                case_id=_coerce_case_id(case_id),
                tenant_id=expected_tenant_id,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        if not records:
            return ()
        ordered = _order_records(records)
        _validate_record_group_tenant_consistency(ordered)
        projections: list[ArbitrationOperationalEventProjection] = []
        for index, record in enumerate(ordered):
            event = project_arbitration_record(
                record=record,
                lineage=_lineage_from_ordered_records(
                    ordered,
                    index=index,
                ),
            )
            append = await self._event_runtime.append_event(
                event,
                expected_tenant_id=expected_tenant_id,
            )
            projections.append(
                ArbitrationOperationalEventProjection(
                    source_record=record,
                    operational_event=append.event,
                )
            )
        return tuple(projections)

    async def _resolve_lineage_for_record(
        self,
        record: ArbitrationRecord,
        *,
        expected_tenant_id: str | None,
    ) -> ArbitrationEvaluationEventLineage:
        records = await self._query_all_records(
            ArbitrationQuery(
                case_id=record.case_id,
                tenant_id=expected_tenant_id,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        if not records:
            return _root_lineage_for_record(record)
        ordered = _order_records(records)
        _validate_record_group_tenant_consistency(ordered)
        for index, candidate in enumerate(ordered):
            if candidate.evaluation_id == record.evaluation_id:
                return _lineage_from_ordered_records(ordered, index=index)
        raise ArbitrationEventProjectionError(
            "arbitration case chronology did not include evaluation "
            f"{record.evaluation_id}"
        )

    async def _query_all_records(
        self,
        query: ArbitrationQuery,
        *,
        expected_tenant_id: str | None,
    ) -> tuple[ArbitrationRecord, ...]:
        limit = 100
        offset = 0
        records: list[ArbitrationRecord] = []
        while True:
            page = await self._arbitration_persistence.list_records(
                ArbitrationQuery(
                    case_id=query.case_id,
                    evaluation_id=query.evaluation_id,
                    outcome=query.outcome,
                    correlation_id=query.correlation_id,
                    request_id=query.request_id,
                    tenant_id=query.tenant_id,
                    limit=limit,
                    offset=offset,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            records.extend(page.records)
            offset += len(page.records)
            if len(page.records) < limit:
                break
            if page.total >= 0 and offset >= page.total:
                break
        return tuple(records)


def make_postgres_dispatch_arbitration_runtime(
    *,
    session: Any,
) -> "DispatchArbitrationRuntime":
    """Compose the Postgres-backed dispatch arbitration facade.

    Kept on this existing Phase 2-I bridge so request/service layers
    can depend on ``app.runtime`` without importing projection modules
    or event-fabric authority directly.
    """

    from app.arbitration.evaluators.builtin import (
        DeadlockDetectionEvaluator,
        EscalationConflictEvaluator,
        FindingConflictEvaluator,
        RecommendationConflictEvaluator,
        SupervisorDisagreementEvaluator,
    )
    from app.arbitration.persistence import PostgresArbitrationPersistence
    from app.arbitration.registry import ArbitrationEvaluatorRegistry
    from app.arbitration.runtime import OperationalArbitrationRuntime
    from app.events import (
        OperationalEventRuntime,
        PostgresOperationalEventPersistence,
    )
    from app.runtime.dispatch_arbitration import DispatchArbitrationRuntime

    arbitration_persistence = PostgresArbitrationPersistence(session)
    event_runtime = OperationalEventRuntime(
        persistence=PostgresOperationalEventPersistence(session)
    )
    return DispatchArbitrationRuntime(
        arbitration_runtime=OperationalArbitrationRuntime(
            registry=ArbitrationEvaluatorRegistry(
                (
                    DeadlockDetectionEvaluator(),
                    EscalationConflictEvaluator(),
                    FindingConflictEvaluator(),
                    RecommendationConflictEvaluator(),
                    SupervisorDisagreementEvaluator(),
                )
            ),
            persistence=arbitration_persistence,
        ),
        projector=ArbitrationOperationalEventProjector(
            arbitration_persistence=arbitration_persistence,
            event_runtime=event_runtime,
        ),
    )


def project_arbitration_record(
    *,
    record: ArbitrationRecord,
    lineage: ArbitrationEvaluationEventLineage | None = None,
) -> OperationalEvent:
    """Convert one persisted arbitration record into an OperationalEvent."""

    event_lineage = lineage or _root_lineage_for_record(record)
    event_id = EventId(str(record.evaluation_id))
    governance_decision_id = (
        str(record.governance_decision_id)
        if record.governance_decision_id is not None
        else None
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.ARBITRATION_EVALUATE,
        substrate=OperationalSubstrate.ARBITRATION,
        causality=EventCausality(
            root_event_id=EventId(event_lineage.root_evaluation_id),
            parent_event_id=(
                EventId(event_lineage.parent_evaluation_id)
                if event_lineage.parent_evaluation_id is not None
                else None
            ),
            depth=event_lineage.depth,
        ),
        chronology=EventChronology(
            runtime_instance_id=record.runtime_instance_id,
            sequence=record.sequence,
            occurred_at=record.started_at,
        ),
        tenant_id=record.tenant_id,
        principal_id=_metadata_optional(record, "principal_id"),
        organization_id=_metadata_optional(record, "organization_id"),
        environment_id=_metadata_optional(record, "environment_id"),
        tenant_authority_source=(
            _metadata_optional(record, "tenant_authority_source")
            or _metadata_optional(record, "authority_source")
        ),
        governance_decision=(
            Decision.ALLOW if governance_decision_id is not None else None
        ),
        governance_decision_id=governance_decision_id,
        metadata=_projection_metadata(record=record, lineage=event_lineage),
    )


def _root_lineage_for_record(
    record: ArbitrationRecord,
) -> ArbitrationEvaluationEventLineage:
    return ArbitrationEvaluationEventLineage(
        root_evaluation_id=str(record.evaluation_id),
        parent_evaluation_id=None,
        depth=0,
    )


def _lineage_from_ordered_records(
    records: tuple[ArbitrationRecord, ...],
    *,
    index: int,
) -> ArbitrationEvaluationEventLineage:
    if not records:
        raise ArbitrationEventProjectionError(
            "arbitration lineage requires at least one record"
        )
    root = records[0]
    parent = records[index - 1] if index > 0 else None
    return ArbitrationEvaluationEventLineage(
        root_evaluation_id=str(root.evaluation_id),
        parent_evaluation_id=(
            str(parent.evaluation_id) if parent is not None else None
        ),
        depth=index,
    )


def _order_records(
    records: tuple[ArbitrationRecord, ...],
) -> tuple[ArbitrationRecord, ...]:
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.started_at,
                str(record.runtime_instance_id),
                record.sequence,
                str(record.evaluation_id),
            ),
        )
    )


def _validate_record_group_tenant_consistency(
    records: tuple[ArbitrationRecord, ...],
) -> None:
    tenant_ids = {record.tenant_id for record in records}
    if len(tenant_ids) > 1:
        raise ArbitrationEventProjectionError(
            "arbitration case contains multiple tenant scopes; refusing "
            "to project a cross-tenant chronology lane"
        )


def _projection_metadata(
    *,
    record: ArbitrationRecord,
    lineage: ArbitrationEvaluationEventLineage,
) -> Mapping[str, Any]:
    return _json_safe(
        {
            "projection_source": "arbitration_evaluation",
            "source_evaluation_id": record.evaluation_id,
            "source_chain_id": record.chain_id,
            "source_case_id": record.case_id,
            "source_runtime_instance_id": record.runtime_instance_id,
            "source_sequence": record.sequence,
            "source_outcome": record.outcome,
            "source_prevailing_authority_level": (
                record.prevailing_authority_level
            ),
            "prevailing_authority_source_substrate": (
                record.prevailing_authority_source_substrate
            ),
            "prevailing_authority_source_id": (
                record.prevailing_authority_source_id
            ),
            "prevailing_authority_verdict": (
                record.prevailing_authority_verdict
            ),
            "source_evaluator_names": record.evaluator_names,
            "source_signal_count": record.signal_count,
            "source_recommendation_count": record.recommendation_count,
            "source_iteration_count": record.iteration_count,
            "source_max_iterations": record.max_iterations,
            "source_correlation_id": record.correlation_id,
            "source_request_id": record.request_id,
            "source_started_at": record.started_at,
            "source_ended_at": record.ended_at,
            "source_latency_ms": record.latency_ms,
            "source_error": record.error,
            "governance_chain_id": record.governance_chain_id,
            "arbitration_lineage": {
                "root_evaluation_id": lineage.root_evaluation_id,
                "parent_evaluation_id": lineage.parent_evaluation_id,
                "depth": lineage.depth,
            },
            "source_record": _record_to_mapping(record),
        }
    )


def _record_to_mapping(record: ArbitrationRecord) -> Mapping[str, Any]:
    return {
        "evaluation_id": record.evaluation_id,
        "chain_id": record.chain_id,
        "case_id": record.case_id,
        "runtime_instance_id": record.runtime_instance_id,
        "sequence": record.sequence,
        "outcome": record.outcome,
        "prevailing_authority_level": record.prevailing_authority_level,
        "prevailing_authority_source_substrate": (
            record.prevailing_authority_source_substrate
        ),
        "prevailing_authority_source_id": record.prevailing_authority_source_id,
        "prevailing_authority_verdict": record.prevailing_authority_verdict,
        "reason": record.reason,
        "evaluator_names": record.evaluator_names,
        "findings": tuple(_finding_to_mapping(f) for f in record.findings),
        "conflicts": tuple(_conflict_to_mapping(c) for c in record.conflicts),
        "deadlock_witnesses": tuple(
            _deadlock_to_mapping(w) for w in record.deadlock_witnesses
        ),
        "signal_count": record.signal_count,
        "recommendation_count": record.recommendation_count,
        "iteration_count": record.iteration_count,
        "max_iterations": record.max_iterations,
        "correlation_id": record.correlation_id,
        "request_id": record.request_id,
        "tenant_id": record.tenant_id,
        "started_at": record.started_at,
        "ended_at": record.ended_at,
        "latency_ms": record.latency_ms,
        "error": record.error,
        "governance_decision_id": record.governance_decision_id,
        "governance_chain_id": record.governance_chain_id,
        "metadata": dict(record.metadata),
    }


def _finding_to_mapping(finding: Any) -> Mapping[str, Any]:
    return {
        "finding_id": finding.finding_id,
        "evaluator_name": finding.evaluator_name,
        "outcome_hint": finding.outcome_hint,
        "code": finding.code,
        "message": finding.message,
        "detected_at": finding.detected_at,
        "related_conflict_id": finding.related_conflict_id,
        "related_deadlock_witness_id": finding.related_deadlock_witness_id,
        "authority": finding.authority,
        "metadata": dict(finding.metadata),
    }


def _conflict_to_mapping(conflict: Any) -> Mapping[str, Any]:
    return {
        "conflict_id": conflict.conflict_id,
        "kind": conflict.kind,
        "participants": conflict.participants,
        "participant_authorities": conflict.participant_authorities,
        "summary": conflict.summary,
        "metadata": dict(conflict.metadata),
    }


def _deadlock_to_mapping(deadlock: Any) -> Mapping[str, Any]:
    return {
        "witness_id": deadlock.witness_id,
        "kind": deadlock.kind,
        "contributing_ids": deadlock.contributing_ids,
        "summary": deadlock.summary,
        "iteration_count": deadlock.iteration_count,
        "metadata": dict(deadlock.metadata),
    }


def _metadata_optional(
    record: ArbitrationRecord,
    key: str,
) -> str | None:
    value = record.metadata.get(key)
    if value is None:
        return None
    text = str(value)
    return text or None


def _coerce_evaluation_id(
    evaluation_id: ArbitrationEvaluationId | str,
) -> ArbitrationEvaluationId:
    if isinstance(evaluation_id, str):
        return as_evaluation_id(evaluation_id)
    return evaluation_id


def _coerce_case_id(case_id: ArbitrationCaseId | str) -> ArbitrationCaseId:
    if isinstance(case_id, str):
        return as_case_id(case_id)
    return case_id


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(value[key])
            for key in sorted(value.keys(), key=str)
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


__all__ = [
    "ArbitrationEvaluationEventLineage",
    "ArbitrationEventProjectionError",
    "ArbitrationOperationalEventProjection",
    "ArbitrationOperationalEventProjector",
    "make_postgres_dispatch_arbitration_runtime",
    "project_arbitration_record",
]
