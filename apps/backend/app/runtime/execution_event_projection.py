"""Phase 2-E execution lineage -> operational event projection bridge.

ExecutionRuntime remains the canonical authority for execution state.
This adapter reads execution records through that authority and writes
an inspectable chronology projection through OperationalEventRuntime.
It never calls workers, Celery, or transport publishers.
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
    derive_event_id,
)
from app.execution import (
    ExecutionAttemptQuery,
    ExecutionAttemptRecord,
    ExecutionAttemptState,
    ExecutionId,
    ExecutionOutboxRecord,
    ExecutionOutboxState,
    ExecutionRecord,
    ExecutionRuntime,
    as_execution_id,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision


_OUTBOX_CREATED_SEQUENCE = 10
_OUTBOX_CLAIMED_SEQUENCE = 11
_OUTBOX_TERMINAL_SEQUENCE = 12
_ATTEMPT_SEQUENCE_BASE = 100
_ATTEMPT_SEQUENCE_STRIDE = 10


class ExecutionEventProjectionError(RuntimeError):
    """Raised when persisted execution lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class ExecutionOperationalEventProjection:
    """One projected execution fact and its canonical event."""

    source_kind: str
    source_id: str
    operational_event: OperationalEvent


@dataclass(frozen=True, slots=True)
class _ExecutionEventFact:
    source_kind: str
    source_id: str
    operational_act: OperationalAct
    sequence: int
    occurred_at: datetime
    parent_event_id: EventId | None
    root_event_id: EventId
    depth: int
    metadata: Mapping[str, Any]


class ExecutionOperationalEventProjector:
    """Projects execution authority records into canonical event fabric."""

    def __init__(
        self,
        *,
        execution_runtime: ExecutionRuntime,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._execution_runtime = execution_runtime
        self._event_runtime = event_runtime

    async def project_execution_events(
        self,
        execution_id: ExecutionId | str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[ExecutionOperationalEventProjection, ...]:
        """Project all visible execution lineage facts for one execution."""

        eid = (
            execution_id
            if not isinstance(execution_id, str)
            else as_execution_id(execution_id)
        )
        execution = await self._execution_runtime.get_execution(
            eid,
            expected_tenant_id=expected_tenant_id,
        )
        if execution is None:
            raise ExecutionEventProjectionError(
                f"unknown execution for event projection: {execution_id}"
            )
        attempts = await self._execution_runtime.list_attempts(
            ExecutionAttemptQuery(execution_id=execution.execution_id),
            expected_tenant_id=expected_tenant_id,
        )
        outbox = await self._execution_runtime.get_outbox_by_execution(
            execution.execution_id,
            expected_tenant_id=expected_tenant_id,
        )
        events = project_execution_records(
            execution=execution,
            attempts=attempts.attempts,
            outbox=outbox,
        )
        projections: list[ExecutionOperationalEventProjection] = []
        for event in events:
            append = await self._event_runtime.append_event(
                event,
                expected_tenant_id=expected_tenant_id,
            )
            projections.append(
                ExecutionOperationalEventProjection(
                    source_kind=str(event.metadata["source_kind"]),
                    source_id=str(event.metadata["source_id"]),
                    operational_event=append.event,
                )
            )
        return tuple(projections)


def project_execution_records(
    *,
    execution: ExecutionRecord,
    attempts: tuple[ExecutionAttemptRecord, ...] = (),
    outbox: ExecutionOutboxRecord | None = None,
) -> tuple[OperationalEvent, ...]:
    """Convert persisted execution lineage to OperationalEvents."""

    runtime_instance_id = uuid.UUID(str(execution.execution_id))
    governance_decision_id = _metadata_optional(
        execution.metadata,
        "governance.decision_id",
        "governance_decision_id",
    )
    request_event_id = _derive_execution_event_id(
        execution=execution,
        operational_act=OperationalAct.EXECUTION_REQUEST,
        sequence=0,
        parent_event_id=None,
    )
    facts: list[_ExecutionEventFact] = [
        _ExecutionEventFact(
            source_kind="execution",
            source_id=str(execution.execution_id),
            operational_act=OperationalAct.EXECUTION_REQUEST,
            sequence=0,
            occurred_at=execution.requested_at,
            parent_event_id=None,
            root_event_id=request_event_id,
            depth=0,
            metadata=_request_metadata(execution),
        )
    ]

    if outbox is not None:
        facts.extend(
            _outbox_facts(
                execution=execution,
                outbox=outbox,
                root_event_id=request_event_id,
            )
        )

    facts.extend(
        _attempt_facts(
            execution=execution,
            attempts=attempts,
            root_event_id=request_event_id,
        )
    )

    return tuple(
        _fact_to_event(
            execution=execution,
            runtime_instance_id=runtime_instance_id,
            governance_decision_id=governance_decision_id,
            fact=fact,
        )
        for fact in sorted(facts, key=lambda f: f.sequence)
    )


def _outbox_facts(
    *,
    execution: ExecutionRecord,
    outbox: ExecutionOutboxRecord,
    root_event_id: EventId,
) -> tuple[_ExecutionEventFact, ...]:
    if outbox.execution_id != execution.execution_id:
        raise ExecutionEventProjectionError(
            "execution outbox belongs to a different execution"
        )

    create_event_id = _derive_execution_event_id(
        execution=execution,
        operational_act=OperationalAct.EXECUTION_OUTBOX_CREATE,
        sequence=_OUTBOX_CREATED_SEQUENCE,
        parent_event_id=root_event_id,
    )
    facts = [
        _ExecutionEventFact(
            source_kind="execution_outbox",
            source_id=str(outbox.outbox_id),
            operational_act=OperationalAct.EXECUTION_OUTBOX_CREATE,
            sequence=_OUTBOX_CREATED_SEQUENCE,
            occurred_at=outbox.created_at,
            parent_event_id=root_event_id,
            root_event_id=root_event_id,
            depth=1,
            metadata=_outbox_metadata(
                execution=execution,
                outbox=outbox,
                transition="created",
            ),
        )
    ]

    claim_event_id: EventId | None = None
    if outbox.claimed_at is not None:
        claim_event_id = _derive_execution_event_id(
            execution=execution,
            operational_act=OperationalAct.EXECUTION_OUTBOX_CLAIM,
            sequence=_OUTBOX_CLAIMED_SEQUENCE,
            parent_event_id=create_event_id,
        )
        facts.append(
            _ExecutionEventFact(
                source_kind="execution_outbox",
                source_id=str(outbox.outbox_id),
                operational_act=OperationalAct.EXECUTION_OUTBOX_CLAIM,
                sequence=_OUTBOX_CLAIMED_SEQUENCE,
                occurred_at=outbox.claimed_at,
                parent_event_id=create_event_id,
                root_event_id=root_event_id,
                depth=2,
                metadata=_outbox_metadata(
                    execution=execution,
                    outbox=outbox,
                    transition="claimed",
                ),
            )
        )

    terminal_fact = _outbox_terminal_fact(
        execution=execution,
        outbox=outbox,
        parent_event_id=claim_event_id,
        create_event_id=create_event_id,
        root_event_id=root_event_id,
    )
    if terminal_fact is not None:
        facts.append(terminal_fact)
    return tuple(facts)


def _outbox_terminal_fact(
    *,
    execution: ExecutionRecord,
    outbox: ExecutionOutboxRecord,
    parent_event_id: EventId | None,
    create_event_id: EventId,
    root_event_id: EventId,
) -> _ExecutionEventFact | None:
    if outbox.state is ExecutionOutboxState.PUBLISHED:
        if outbox.published_at is None:
            raise ExecutionEventProjectionError(
                "published outbox is missing published_at"
            )
        parent = _require_outbox_claim_parent(
            outbox=outbox,
            parent_event_id=parent_event_id,
            create_event_id=create_event_id,
        )
        return _ExecutionEventFact(
            source_kind="execution_outbox",
            source_id=str(outbox.outbox_id),
            operational_act=OperationalAct.EXECUTION_OUTBOX_PUBLISH,
            sequence=_OUTBOX_TERMINAL_SEQUENCE,
            occurred_at=outbox.published_at,
            parent_event_id=parent,
            root_event_id=root_event_id,
            depth=3,
            metadata=_outbox_metadata(
                execution=execution,
                outbox=outbox,
                transition="published",
            ),
        )
    if outbox.state is ExecutionOutboxState.FAILED:
        failed_at = _parse_optional_datetime(outbox.metadata.get("failed_at"))
        if failed_at is None:
            raise ExecutionEventProjectionError(
                "failed outbox is missing metadata['failed_at']"
            )
        parent = _require_outbox_claim_parent(
            outbox=outbox,
            parent_event_id=parent_event_id,
            create_event_id=create_event_id,
        )
        return _ExecutionEventFact(
            source_kind="execution_outbox",
            source_id=str(outbox.outbox_id),
            operational_act=OperationalAct.EXECUTION_OUTBOX_FAIL,
            sequence=_OUTBOX_TERMINAL_SEQUENCE,
            occurred_at=failed_at,
            parent_event_id=parent,
            root_event_id=root_event_id,
            depth=3,
            metadata=_outbox_metadata(
                execution=execution,
                outbox=outbox,
                transition="failed",
            ),
        )
    return None


def _attempt_facts(
    *,
    execution: ExecutionRecord,
    attempts: tuple[ExecutionAttemptRecord, ...],
    root_event_id: EventId,
) -> tuple[_ExecutionEventFact, ...]:
    ordered = tuple(
        sorted(attempts, key=lambda a: (a.attempt_number, a.started_at))
    )
    terminal_event_ids: dict[object, EventId] = {}
    terminal_depths: dict[object, int] = {}
    facts: list[_ExecutionEventFact] = []
    for attempt in ordered:
        if attempt.execution_id != execution.execution_id:
            raise ExecutionEventProjectionError(
                "execution attempt belongs to a different execution"
            )
        start_sequence = _attempt_start_sequence(attempt.attempt_number)
        if attempt.attempt_number == 1:
            parent_event_id = root_event_id
            depth = 1
        else:
            previous_id = attempt.previous_attempt_id
            if previous_id is None or previous_id not in terminal_event_ids:
                raise ExecutionEventProjectionError(
                    "execution attempt retry lineage is incomplete"
                )
            parent_event_id = terminal_event_ids[previous_id]
            depth = terminal_depths[previous_id] + 1
        claim_event_id = _derive_execution_event_id(
            execution=execution,
            operational_act=OperationalAct.EXECUTION_CLAIM,
            sequence=start_sequence,
            parent_event_id=parent_event_id,
        )
        facts.append(
            _ExecutionEventFact(
                source_kind="execution_attempt",
                source_id=str(attempt.attempt_id),
                operational_act=OperationalAct.EXECUTION_CLAIM,
                sequence=start_sequence,
                occurred_at=attempt.started_at,
                parent_event_id=parent_event_id,
                root_event_id=root_event_id,
                depth=depth,
                metadata=_attempt_metadata(
                    execution=execution,
                    attempt=attempt,
                    transition="claimed",
                ),
            )
        )
        terminal_fact = _attempt_terminal_fact(
            execution=execution,
            attempt=attempt,
            claim_event_id=claim_event_id,
            root_event_id=root_event_id,
            depth=depth + 1,
        )
        if terminal_fact is not None:
            facts.append(terminal_fact)
            terminal_event_ids[attempt.attempt_id] = _derive_execution_event_id(
                execution=execution,
                operational_act=terminal_fact.operational_act,
                sequence=terminal_fact.sequence,
                parent_event_id=claim_event_id,
            )
            terminal_depths[attempt.attempt_id] = terminal_fact.depth
    return tuple(facts)


def _attempt_terminal_fact(
    *,
    execution: ExecutionRecord,
    attempt: ExecutionAttemptRecord,
    claim_event_id: EventId,
    root_event_id: EventId,
    depth: int,
) -> _ExecutionEventFact | None:
    sequence = _attempt_terminal_sequence(attempt.attempt_number)
    if attempt.state is ExecutionAttemptState.COMPLETED:
        if attempt.completed_at is None:
            raise ExecutionEventProjectionError(
                "completed execution attempt is missing completed_at"
            )
        return _ExecutionEventFact(
            source_kind="execution_attempt",
            source_id=str(attempt.attempt_id),
            operational_act=OperationalAct.EXECUTION_COMPLETE,
            sequence=sequence,
            occurred_at=attempt.completed_at,
            parent_event_id=claim_event_id,
            root_event_id=root_event_id,
            depth=depth,
            metadata=_attempt_metadata(
                execution=execution,
                attempt=attempt,
                transition="completed",
            ),
        )
    if attempt.state is ExecutionAttemptState.FAILED:
        if attempt.failed_at is None:
            raise ExecutionEventProjectionError(
                "failed execution attempt is missing failed_at"
            )
        act = (
            OperationalAct.EXECUTION_RECOVER
            if "recovery.recovered_at" in attempt.metadata
            else OperationalAct.EXECUTION_FAIL
        )
        return _ExecutionEventFact(
            source_kind="execution_attempt",
            source_id=str(attempt.attempt_id),
            operational_act=act,
            sequence=sequence,
            occurred_at=attempt.failed_at,
            parent_event_id=claim_event_id,
            root_event_id=root_event_id,
            depth=depth,
            metadata=_attempt_metadata(
                execution=execution,
                attempt=attempt,
                transition=(
                    "recovered"
                    if act is OperationalAct.EXECUTION_RECOVER
                    else "failed"
                ),
            ),
        )
    if attempt.state is ExecutionAttemptState.DEAD_LETTERED:
        if attempt.failed_at is None:
            raise ExecutionEventProjectionError(
                "dead-lettered execution attempt is missing failed_at"
            )
        return _ExecutionEventFact(
            source_kind="execution_attempt",
            source_id=str(attempt.attempt_id),
            operational_act=OperationalAct.EXECUTION_DEAD_LETTER,
            sequence=sequence,
            occurred_at=attempt.failed_at,
            parent_event_id=claim_event_id,
            root_event_id=root_event_id,
            depth=depth,
            metadata=_attempt_metadata(
                execution=execution,
                attempt=attempt,
                transition="dead_lettered",
            ),
        )
    return None


def _fact_to_event(
    *,
    execution: ExecutionRecord,
    runtime_instance_id: uuid.UUID,
    governance_decision_id: str | None,
    fact: _ExecutionEventFact,
) -> OperationalEvent:
    event_id = _derive_execution_event_id(
        execution=execution,
        operational_act=fact.operational_act,
        sequence=fact.sequence,
        parent_event_id=fact.parent_event_id,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=fact.operational_act,
        substrate=OperationalSubstrate.EXECUTION,
        causality=EventCausality(
            root_event_id=fact.root_event_id,
            parent_event_id=fact.parent_event_id,
            depth=fact.depth,
        ),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=fact.sequence,
            occurred_at=fact.occurred_at,
        ),
        tenant_id=execution.tenant_id,
        principal_id=_authority_optional(execution, "principal_id"),
        organization_id=_authority_optional(execution, "organization_id"),
        environment_id=_authority_optional(execution, "environment_id"),
        tenant_authority_source=(
            _authority_optional(execution, "tenant_authority_source")
            or _authority_optional(execution, "authority_source")
        ),
        governance_decision=(
            Decision.ALLOW if governance_decision_id is not None else None
        ),
        governance_decision_id=governance_decision_id,
        metadata={
            **dict(fact.metadata),
            "source_kind": fact.source_kind,
            "source_id": fact.source_id,
            "projection_source": "execution_lineage",
        },
    )


def _request_metadata(execution: ExecutionRecord) -> Mapping[str, Any]:
    return {
        "transition": "requested",
        "execution_id": str(execution.execution_id),
        "execution_kind": execution.kind.value,
        "dispatch_id": execution.dispatch_id,
        "session_id": execution.session_id,
        "tenant_id": execution.tenant_id,
        "requested_at": execution.requested_at.isoformat(),
    }


def _outbox_metadata(
    *,
    execution: ExecutionRecord,
    outbox: ExecutionOutboxRecord,
    transition: str,
) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {
        "transition": transition,
        "execution_id": str(execution.execution_id),
        "outbox_id": str(outbox.outbox_id),
        "created_at": outbox.created_at.isoformat(),
    }
    if transition == "created":
        metadata["outbox_state"] = ExecutionOutboxState.PENDING.value
        metadata["publish_attempt_count"] = 0
    elif transition == "claimed":
        metadata["outbox_state"] = ExecutionOutboxState.PUBLISHING.value
        metadata["claimed_at"] = (
            outbox.claimed_at.isoformat()
            if outbox.claimed_at is not None
            else None
        )
        metadata["publisher_id"] = outbox.publisher_id
        metadata["publish_attempt_count"] = outbox.publish_attempt_count
    elif transition == "published":
        metadata["outbox_state"] = ExecutionOutboxState.PUBLISHED.value
        metadata["claimed_at"] = (
            outbox.claimed_at.isoformat()
            if outbox.claimed_at is not None
            else None
        )
        metadata["published_at"] = (
            outbox.published_at.isoformat()
            if outbox.published_at is not None
            else None
        )
        metadata["publisher_id"] = outbox.publisher_id
        metadata["publish_attempt_count"] = outbox.publish_attempt_count
    elif transition == "failed":
        metadata["outbox_state"] = ExecutionOutboxState.FAILED.value
        metadata["claimed_at"] = (
            outbox.claimed_at.isoformat()
            if outbox.claimed_at is not None
            else None
        )
        metadata["publisher_id"] = outbox.publisher_id
        metadata["publish_attempt_count"] = outbox.publish_attempt_count
        metadata["last_error"] = outbox.last_error
        failed_at = outbox.metadata.get("failed_at")
        if failed_at is not None:
            metadata["failed_at"] = str(failed_at)
    return metadata


def _attempt_metadata(
    *,
    execution: ExecutionRecord,
    attempt: ExecutionAttemptRecord,
    transition: str,
) -> Mapping[str, Any]:
    metadata: dict[str, Any] = {
        "transition": transition,
        "execution_id": str(execution.execution_id),
        "attempt_id": str(attempt.attempt_id),
        "attempt_number": attempt.attempt_number,
        "worker_id": attempt.worker_id,
        "started_at": attempt.started_at.isoformat(),
        "previous_attempt_id": (
            str(attempt.previous_attempt_id)
            if attempt.previous_attempt_id is not None
            else None
        ),
    }
    if transition == "claimed":
        metadata["attempt_state"] = ExecutionAttemptState.RUNNING.value
    elif transition == "completed":
        metadata["attempt_state"] = ExecutionAttemptState.COMPLETED.value
        metadata["completed_at"] = (
            attempt.completed_at.isoformat()
            if attempt.completed_at is not None
            else None
        )
        metadata["result"] = attempt.result.to_dict()
    elif transition in {"failed", "recovered"}:
        metadata["attempt_state"] = ExecutionAttemptState.FAILED.value
        metadata["failed_at"] = (
            attempt.failed_at.isoformat()
            if attempt.failed_at is not None
            else None
        )
        metadata["retry_requested"] = attempt.retry_requested
        metadata["error"] = attempt.error
        metadata["attempt_metadata"] = dict(attempt.metadata)
    elif transition == "dead_lettered":
        metadata["attempt_state"] = ExecutionAttemptState.DEAD_LETTERED.value
        metadata["failed_at"] = (
            attempt.failed_at.isoformat()
            if attempt.failed_at is not None
            else None
        )
        metadata["retry_requested"] = attempt.retry_requested
        metadata["error"] = attempt.error
        metadata["result"] = attempt.result.to_dict()
        metadata["attempt_metadata"] = dict(attempt.metadata)
    return metadata


def _derive_execution_event_id(
    *,
    execution: ExecutionRecord,
    operational_act: OperationalAct,
    sequence: int,
    parent_event_id: EventId | None,
) -> EventId:
    return derive_event_id(
        operational_act=operational_act.value,
        substrate=OperationalSubstrate.EXECUTION.value,
        runtime_instance_id=uuid.UUID(str(execution.execution_id)),
        sequence=sequence,
        tenant_id=execution.tenant_id,
        parent_event_id=parent_event_id,
    )


def _attempt_start_sequence(attempt_number: int) -> int:
    _validate_attempt_number(attempt_number)
    return _ATTEMPT_SEQUENCE_BASE + (
        (attempt_number - 1) * _ATTEMPT_SEQUENCE_STRIDE
    )


def _attempt_terminal_sequence(attempt_number: int) -> int:
    return _attempt_start_sequence(attempt_number) + 1


def _validate_attempt_number(attempt_number: int) -> None:
    if attempt_number < 1:
        raise ExecutionEventProjectionError("attempt_number must be >= 1")


def _require_outbox_claim_parent(
    *,
    outbox: ExecutionOutboxRecord,
    parent_event_id: EventId | None,
    create_event_id: EventId,
) -> EventId:
    if parent_event_id is None:
        raise ExecutionEventProjectionError(
            f"outbox {outbox.outbox_id} terminal state lacks claim lineage"
        )
    if parent_event_id == create_event_id:
        raise ExecutionEventProjectionError(
            f"outbox {outbox.outbox_id} terminal state lacks claim lineage"
        )
    return parent_event_id


def _parse_optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _metadata_optional(
    metadata: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return None


def _authority_optional(
    execution: ExecutionRecord,
    key: str,
) -> str | None:
    return _metadata_optional(execution.metadata, key)


__all__ = [
    "ExecutionEventProjectionError",
    "ExecutionOperationalEventProjection",
    "ExecutionOperationalEventProjector",
    "project_execution_records",
]
