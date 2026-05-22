"""Cross-runtime lineage normalization for canonical OperationalEvents.

The normalizer is a read-only view over the event fabric. It turns
already-persisted event metadata into typed lineage edges without
mutating events, rewriting causality, or creating a second chronology
authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from app.events.event import OperationalEvent
from app.events.exceptions import EventFabricError
from app.events.identity import EventId
from app.events.ordering import operational_event_replay_sort_key
from app.events.persistence import OperationalEventQuery
from app.events.runtime import OperationalEventRuntime
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct


class OperationalLineageRelation(StrEnum):
    """Closed vocabulary of normalized event-lineage relations."""

    LOCAL_PARENT = "local_parent"
    GOVERNED_BY = "governed_by"
    EXECUTION_FOR_SESSION = "execution_for_session"
    SUPERVISES_EXECUTION = "supervises_execution"
    ARBITRATES_AUTHORITY = "arbitrates_authority"


class OperationalLineageError(EventFabricError):
    """Raised when lineage references violate event-fabric invariants."""


@dataclass(frozen=True, slots=True)
class OperationalLineageEdge:
    """Resolved relationship between two canonical events."""

    source_event_id: EventId
    target_event_id: EventId
    relation: OperationalLineageRelation
    source_substrate: OperationalSubstrate
    target_substrate: OperationalSubstrate
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_event_id == self.target_event_id:
            raise OperationalLineageError(
                "lineage edge cannot point an event at itself"
            )


@dataclass(frozen=True, slots=True)
class OperationalLineageUnresolvedReference:
    """A lineage reference whose target event is absent from the view."""

    source_event_id: EventId
    relation: OperationalLineageRelation
    target_key: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperationalLineageGraph:
    """Read-only lineage graph for a set of canonical events."""

    events: tuple[OperationalEvent, ...]
    edges: tuple[OperationalLineageEdge, ...] = ()
    unresolved: tuple[OperationalLineageUnresolvedReference, ...] = ()


class OperationalLineageRuntime:
    """Read-only lineage normalizer over OperationalEventRuntime."""

    def __init__(self, *, event_runtime: OperationalEventRuntime) -> None:
        self._event_runtime = event_runtime

    async def build_graph(
        self,
        query: OperationalEventQuery | None = None,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalLineageGraph:
        """Read matching events and normalize their lineage references."""

        events = await self._list_all_events(
            query or OperationalEventQuery(),
            expected_tenant_id=expected_tenant_id,
        )
        return normalize_operational_lineage(events)

    async def _list_all_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None,
    ) -> tuple[OperationalEvent, ...]:
        limit = 100
        offset = 0
        events: list[OperationalEvent] = []
        while True:
            page = await self._event_runtime.list_events(
                OperationalEventQuery(
                    event_id=query.event_id,
                    operational_act=query.operational_act,
                    substrate=query.substrate,
                    tenant_id=query.tenant_id,
                    runtime_instance_id=query.runtime_instance_id,
                    root_event_id=query.root_event_id,
                    parent_event_id=query.parent_event_id,
                    governance_decision_id=query.governance_decision_id,
                    occurred_after_or_at=query.occurred_after_or_at,
                    occurred_before_or_at=query.occurred_before_or_at,
                    limit=limit,
                    offset=offset,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            events.extend(page.events)
            offset += len(page.events)
            if len(page.events) < limit:
                break
            if page.total >= 0 and offset >= page.total:
                break
        return tuple(events)


def normalize_operational_lineage(
    events: tuple[OperationalEvent, ...],
) -> OperationalLineageGraph:
    """Build a deterministic lineage graph from canonical events."""

    ordered = tuple(sorted(events, key=_event_sort_key))
    by_id = {event.event_id: event for event in ordered}
    session_roots = _session_roots_by_session_id(ordered)
    execution_roots = _execution_roots_by_execution_id(ordered)
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ] = {}
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ] = {}

    for event in ordered:
        _add_local_parent_edges(
            event=event,
            by_id=by_id,
            edges=edges,
            unresolved=unresolved,
        )
        _add_governance_edges(
            event=event,
            by_id=by_id,
            edges=edges,
            unresolved=unresolved,
        )
        _add_execution_session_edges(
            event=event,
            session_roots=session_roots,
            edges=edges,
            unresolved=unresolved,
        )
        _add_supervisor_execution_edges(
            event=event,
            execution_roots=execution_roots,
            edges=edges,
            unresolved=unresolved,
        )
        _add_arbitration_authority_edges(
            event=event,
            by_id=by_id,
            execution_roots=execution_roots,
            edges=edges,
            unresolved=unresolved,
        )

    return OperationalLineageGraph(
        events=ordered,
        edges=tuple(sorted(edges.values(), key=_edge_sort_key)),
        unresolved=tuple(
            sorted(unresolved.values(), key=_unresolved_sort_key)
        ),
    )


def _add_local_parent_edges(
    *,
    event: OperationalEvent,
    by_id: Mapping[EventId, OperationalEvent],
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
) -> None:
    parent_id = event.causality.parent_event_id
    if parent_id is None:
        return
    _resolve_or_record(
        source=event,
        relation=OperationalLineageRelation.LOCAL_PARENT,
        target_key=str(parent_id),
        target=by_id.get(parent_id),
        edges=edges,
        unresolved=unresolved,
        metadata={"depth": event.causality.depth},
    )


def _add_governance_edges(
    *,
    event: OperationalEvent,
    by_id: Mapping[EventId, OperationalEvent],
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
) -> None:
    decision_id = event.governance_decision_id
    if decision_id is None or decision_id == event.event_id:
        return
    target_key = str(decision_id)
    _resolve_or_record(
        source=event,
        relation=OperationalLineageRelation.GOVERNED_BY,
        target_key=target_key,
        target=by_id.get(EventId(target_key)),
        edges=edges,
        unresolved=unresolved,
        metadata={"governance_decision_id": target_key},
        expected_target_substrate=OperationalSubstrate.GOVERNANCE,
    )


def _add_execution_session_edges(
    *,
    event: OperationalEvent,
    session_roots: Mapping[str, OperationalEvent],
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
) -> None:
    if event.operational_act is not OperationalAct.EXECUTION_REQUEST:
        return
    session_id = _metadata_text(event.metadata, "session_id")
    if session_id is None:
        return
    _resolve_or_record(
        source=event,
        relation=OperationalLineageRelation.EXECUTION_FOR_SESSION,
        target_key=session_id,
        target=session_roots.get(session_id),
        edges=edges,
        unresolved=unresolved,
        metadata={"session_id": session_id},
        expected_target_substrate=OperationalSubstrate.SESSION,
    )


def _add_supervisor_execution_edges(
    *,
    event: OperationalEvent,
    execution_roots: Mapping[str, OperationalEvent],
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
) -> None:
    if event.operational_act is not OperationalAct.SUPERVISOR_INSPECT:
        return
    execution_id = _metadata_text(event.metadata, "source_execution_id")
    if execution_id is None:
        return
    _resolve_or_record(
        source=event,
        relation=OperationalLineageRelation.SUPERVISES_EXECUTION,
        target_key=execution_id,
        target=execution_roots.get(execution_id),
        edges=edges,
        unresolved=unresolved,
        metadata={"execution_id": execution_id},
        expected_target_substrate=OperationalSubstrate.EXECUTION,
    )


def _add_arbitration_authority_edges(
    *,
    event: OperationalEvent,
    by_id: Mapping[EventId, OperationalEvent],
    execution_roots: Mapping[str, OperationalEvent],
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
) -> None:
    if event.operational_act is not OperationalAct.ARBITRATION_EVALUATE:
        return
    source_substrate = _metadata_text(
        event.metadata,
        "prevailing_authority_source_substrate",
    )
    source_id = _metadata_text(
        event.metadata,
        "prevailing_authority_source_id",
    )
    if source_substrate is None or source_id is None:
        return

    target_key = f"{source_substrate}:{source_id}"
    target: OperationalEvent | None = None
    expected_target_substrate: OperationalSubstrate | None = None
    if source_substrate == OperationalSubstrate.GOVERNANCE.value:
        target_key = source_id
        target = by_id.get(EventId(source_id))
        expected_target_substrate = OperationalSubstrate.GOVERNANCE
    elif source_substrate == OperationalSubstrate.SUPERVISOR.value:
        target_key = source_id
        target = by_id.get(EventId(source_id))
        expected_target_substrate = OperationalSubstrate.SUPERVISOR
    elif source_substrate == OperationalSubstrate.ARBITRATION.value:
        target_key = source_id
        target = by_id.get(EventId(source_id))
        expected_target_substrate = OperationalSubstrate.ARBITRATION
    elif source_substrate == OperationalSubstrate.EXECUTION.value:
        target_key = source_id
        target = execution_roots.get(source_id)
        expected_target_substrate = OperationalSubstrate.EXECUTION
    if target is event:
        return

    _resolve_or_record(
        source=event,
        relation=OperationalLineageRelation.ARBITRATES_AUTHORITY,
        target_key=target_key,
        target=target,
        edges=edges,
        unresolved=unresolved,
        metadata={
            "prevailing_authority_source_substrate": source_substrate,
            "prevailing_authority_source_id": source_id,
        },
        expected_target_substrate=expected_target_substrate,
    )


def _resolve_or_record(
    *,
    source: OperationalEvent,
    relation: OperationalLineageRelation,
    target_key: str,
    target: OperationalEvent | None,
    edges: dict[
        tuple[EventId, OperationalLineageRelation, EventId],
        OperationalLineageEdge,
    ],
    unresolved: dict[
        tuple[EventId, OperationalLineageRelation, str],
        OperationalLineageUnresolvedReference,
    ],
    metadata: Mapping[str, Any],
    expected_target_substrate: OperationalSubstrate | None = None,
) -> None:
    if target is None:
        unresolved[(source.event_id, relation, target_key)] = (
            OperationalLineageUnresolvedReference(
                source_event_id=source.event_id,
                relation=relation,
                target_key=target_key,
                metadata=dict(metadata),
            )
        )
        return
    _validate_edge_target(
        source=source,
        target=target,
        relation=relation,
        expected_target_substrate=expected_target_substrate,
    )
    edge = OperationalLineageEdge(
        source_event_id=source.event_id,
        target_event_id=target.event_id,
        relation=relation,
        source_substrate=source.substrate,
        target_substrate=target.substrate,
        metadata=dict(metadata),
    )
    edges[(edge.source_event_id, edge.relation, edge.target_event_id)] = edge


def _validate_edge_target(
    *,
    source: OperationalEvent,
    target: OperationalEvent,
    relation: OperationalLineageRelation,
    expected_target_substrate: OperationalSubstrate | None,
) -> None:
    if expected_target_substrate is not None and target.substrate is not expected_target_substrate:
        raise OperationalLineageError(
            f"{relation.value} target {target.event_id!r} is "
            f"{target.substrate.value!r}, expected "
            f"{expected_target_substrate.value!r}"
        )
    if source.tenant_id != target.tenant_id:
        raise OperationalLineageError(
            f"{relation.value} crosses tenant scopes: "
            f"{source.tenant_id!r} -> {target.tenant_id!r}"
        )


def _session_roots_by_session_id(
    events: tuple[OperationalEvent, ...],
) -> dict[str, OperationalEvent]:
    roots: dict[str, OperationalEvent] = {}
    for event in events:
        if event.substrate is not OperationalSubstrate.SESSION:
            continue
        if event.operational_act is not OperationalAct.SESSION_OPEN:
            continue
        session_id = _metadata_text(event.metadata, "source_session_id")
        if session_id is None:
            continue
        roots.setdefault(session_id, event)
    return roots


def _execution_roots_by_execution_id(
    events: tuple[OperationalEvent, ...],
) -> dict[str, OperationalEvent]:
    roots: dict[str, OperationalEvent] = {}
    for event in events:
        if event.substrate is not OperationalSubstrate.EXECUTION:
            continue
        if event.operational_act is not OperationalAct.EXECUTION_REQUEST:
            continue
        execution_id = _metadata_text(event.metadata, "execution_id")
        if execution_id is None:
            continue
        roots.setdefault(execution_id, event)
    return roots


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    text = str(value)
    return text or None


def _event_sort_key(
    event: OperationalEvent,
) -> tuple[str, int, str, int, str]:
    return operational_event_replay_sort_key(event)


def _edge_sort_key(
    edge: OperationalLineageEdge,
) -> tuple[str, str, str]:
    return (
        str(edge.source_event_id),
        edge.relation.value,
        str(edge.target_event_id),
    )


def _unresolved_sort_key(
    reference: OperationalLineageUnresolvedReference,
) -> tuple[str, str, str]:
    return (
        str(reference.source_event_id),
        reference.relation.value,
        reference.target_key,
    )


__all__ = [
    "OperationalLineageEdge",
    "OperationalLineageError",
    "OperationalLineageGraph",
    "OperationalLineageRelation",
    "OperationalLineageRuntime",
    "OperationalLineageUnresolvedReference",
    "normalize_operational_lineage",
]
