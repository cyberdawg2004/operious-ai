"""Canonical replay/read surface for operational events.

This runtime is deliberately read-only. It reconstructs deterministic
replay traces from already-persisted :class:`OperationalEvent` rows and
reports integrity findings without mutating chronology, projecting new
events, or borrowing authority from sibling runtimes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from app.events.event import OperationalEvent
from app.events.identity import EventId
from app.events.lineage import (
    OperationalLineageGraph,
    OperationalLineageError,
    OperationalLineageRelation,
    normalize_operational_lineage,
)
from app.events.ordering import operational_event_replay_sort_key
from app.events.persistence import OperationalEventQuery
from app.events.runtime import OperationalEventRuntime


class OperationalReplayStatus(StrEnum):
    """Replay trace integrity status."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INVALID = "invalid"


class OperationalReplayFindingSeverity(StrEnum):
    """Severity of a replay integrity finding."""

    WARNING = "warning"
    ERROR = "error"


class OperationalReplayFindingCode(StrEnum):
    """Closed vocabulary for event replay integrity findings."""

    EVENT_NOT_FOUND = "event_not_found"
    EMPTY_TRACE = "empty_trace"
    MISSING_ROOT = "missing_root"
    MISSING_PARENT = "missing_parent"
    ROOT_MISMATCH = "root_mismatch"
    DEPTH_MISMATCH = "depth_mismatch"
    TENANT_MISMATCH = "tenant_mismatch"
    LINEAGE_INVALID = "lineage_invalid"
    LINEAGE_UNRESOLVED = "lineage_unresolved"


@dataclass(frozen=True, slots=True)
class OperationalReplayFinding:
    """A replay-integrity observation for a canonical event trace."""

    code: OperationalReplayFindingCode
    severity: OperationalReplayFindingSeverity
    message: str
    event_id: EventId | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=dict[str, Any]
    )


@dataclass(frozen=True, slots=True)
class OperationalReplayTrace:
    """Deterministic read model for a replayable operational trace."""

    root_event_id: EventId | None
    events: tuple[OperationalEvent, ...]
    lineage: OperationalLineageGraph
    findings: tuple[OperationalReplayFinding, ...]
    status: OperationalReplayStatus


class OperationalReplayRuntime:
    """Read-only replay runtime over :class:`OperationalEventRuntime`."""

    def __init__(self, *, event_runtime: OperationalEventRuntime) -> None:
        self._event_runtime = event_runtime

    async def load_event_trace(
        self,
        event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalReplayTrace:
        """Load the causal replay trace that contains ``event_id``."""

        event = await self._event_runtime.get_event(
            event_id,
            expected_tenant_id=expected_tenant_id,
        )
        if event is None:
            return _build_trace(
                root_event_id=None,
                events=(),
                expected_tenant_id=expected_tenant_id,
                preflight_findings=(
                    OperationalReplayFinding(
                        code=OperationalReplayFindingCode.EVENT_NOT_FOUND,
                        severity=OperationalReplayFindingSeverity.ERROR,
                        event_id=event_id,
                        message=(
                            "event replay trace cannot be loaded; "
                            "event not found"
                        ),
                    ),
                ),
            )
        return await self.load_causal_trace(
            event.causality.root_event_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def load_causal_trace(
        self,
        root_event_id: EventId,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalReplayTrace:
        """Load a deterministic replay trace for one causal root."""

        events = await self._list_all_events(
            OperationalEventQuery(root_event_id=root_event_id),
            expected_tenant_id=expected_tenant_id,
        )
        return _build_trace(
            root_event_id=root_event_id,
            events=events,
            expected_tenant_id=expected_tenant_id,
        )

    async def load_window(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> OperationalReplayTrace:
        """Load a deterministic replay/read window for an event query."""

        events = await self._list_all_events(
            query,
            expected_tenant_id=expected_tenant_id,
        )
        return _build_trace(
            root_event_id=query.root_event_id,
            events=events,
            expected_tenant_id=expected_tenant_id,
        )

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


def _build_trace(
    *,
    root_event_id: EventId | None,
    events: tuple[OperationalEvent, ...],
    expected_tenant_id: str | None,
    preflight_findings: tuple[OperationalReplayFinding, ...] = (),
) -> OperationalReplayTrace:
    ordered = tuple(sorted(events, key=operational_event_replay_sort_key))
    try:
        lineage = normalize_operational_lineage(ordered)
        lineage_findings = _lineage_findings(lineage)
    except OperationalLineageError as exc:
        lineage = OperationalLineageGraph(events=ordered)
        lineage_findings = (
            OperationalReplayFinding(
                code=OperationalReplayFindingCode.LINEAGE_INVALID,
                severity=OperationalReplayFindingSeverity.ERROR,
                message=str(exc),
            ),
        )
    findings = (
        *preflight_findings,
        *_causality_findings(
            events=ordered,
            root_event_id=root_event_id,
            expected_tenant_id=expected_tenant_id,
        ),
        *lineage_findings,
    )
    return OperationalReplayTrace(
        root_event_id=root_event_id,
        events=ordered,
        lineage=lineage,
        findings=findings,
        status=_status_from_findings(findings),
    )


def _causality_findings(
    *,
    events: tuple[OperationalEvent, ...],
    root_event_id: EventId | None,
    expected_tenant_id: str | None,
) -> tuple[OperationalReplayFinding, ...]:
    if not events:
        return (
            OperationalReplayFinding(
                code=OperationalReplayFindingCode.EMPTY_TRACE,
                severity=OperationalReplayFindingSeverity.WARNING,
                message="event replay trace contains no events",
                metadata=(
                    {"root_event_id": str(root_event_id)}
                    if root_event_id is not None
                    else {}
                ),
            ),
        )

    by_id = {event.event_id: event for event in events}
    findings: list[OperationalReplayFinding] = []
    if root_event_id is not None and root_event_id not in by_id:
        findings.append(
            OperationalReplayFinding(
                code=OperationalReplayFindingCode.MISSING_ROOT,
                severity=OperationalReplayFindingSeverity.ERROR,
                event_id=root_event_id,
                message="causal replay trace is missing its root event",
                metadata={"root_event_id": str(root_event_id)},
            )
        )

    for event in events:
        if (
            expected_tenant_id is not None
            and event.tenant_id != expected_tenant_id
        ):
            findings.append(
                OperationalReplayFinding(
                    code=OperationalReplayFindingCode.TENANT_MISMATCH,
                    severity=OperationalReplayFindingSeverity.ERROR,
                    event_id=event.event_id,
                    message="event tenant_id does not match replay tenant scope",
                    metadata={
                        "expected_tenant_id": expected_tenant_id,
                        "event_tenant_id": event.tenant_id,
                    },
                )
            )
        parent_id = event.causality.parent_event_id
        if parent_id is None:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            findings.append(
                OperationalReplayFinding(
                    code=OperationalReplayFindingCode.MISSING_PARENT,
                    severity=OperationalReplayFindingSeverity.ERROR,
                    event_id=event.event_id,
                    message="causal replay trace is missing an event parent",
                    metadata={"parent_event_id": str(parent_id)},
                )
            )
            continue
        if parent.causality.root_event_id != event.causality.root_event_id:
            findings.append(
                OperationalReplayFinding(
                    code=OperationalReplayFindingCode.ROOT_MISMATCH,
                    severity=OperationalReplayFindingSeverity.ERROR,
                    event_id=event.event_id,
                    message="event parent belongs to a different causal root",
                    metadata={
                        "parent_event_id": str(parent.event_id),
                        "parent_root_event_id": str(
                            parent.causality.root_event_id
                        ),
                        "event_root_event_id": str(event.causality.root_event_id),
                    },
                )
            )
        if event.causality.depth != parent.causality.depth + 1:
            findings.append(
                OperationalReplayFinding(
                    code=OperationalReplayFindingCode.DEPTH_MISMATCH,
                    severity=OperationalReplayFindingSeverity.ERROR,
                    event_id=event.event_id,
                    message="event causality depth is not parent depth + 1",
                    metadata={
                        "parent_event_id": str(parent.event_id),
                        "parent_depth": parent.causality.depth,
                        "event_depth": event.causality.depth,
                    },
                )
            )
    return tuple(sorted(findings, key=_finding_sort_key))


def _lineage_findings(
    lineage: OperationalLineageGraph,
) -> tuple[OperationalReplayFinding, ...]:
    findings = [
        OperationalReplayFinding(
            code=OperationalReplayFindingCode.LINEAGE_UNRESOLVED,
            severity=OperationalReplayFindingSeverity.WARNING,
            event_id=reference.source_event_id,
            message=(
                "event replay trace contains an unresolved "
                "lineage reference"
            ),
            metadata={
                "relation": reference.relation.value,
                "target_key": reference.target_key,
                **dict(reference.metadata),
            },
        )
        for reference in lineage.unresolved
        if reference.relation is not OperationalLineageRelation.LOCAL_PARENT
    ]
    return tuple(sorted(findings, key=_finding_sort_key))


def _status_from_findings(
    findings: tuple[OperationalReplayFinding, ...],
) -> OperationalReplayStatus:
    if any(
        finding.severity is OperationalReplayFindingSeverity.ERROR
        for finding in findings
    ):
        return OperationalReplayStatus.INVALID
    if findings:
        return OperationalReplayStatus.PARTIAL
    return OperationalReplayStatus.COMPLETE


def _finding_sort_key(
    finding: OperationalReplayFinding,
) -> tuple[str, str, str]:
    return (
        "" if finding.event_id is None else str(finding.event_id),
        finding.code.value,
        finding.message,
    )


__all__ = [
    "OperationalReplayFinding",
    "OperationalReplayFindingCode",
    "OperationalReplayFindingSeverity",
    "OperationalReplayRuntime",
    "OperationalReplayStatus",
    "OperationalReplayTrace",
]
