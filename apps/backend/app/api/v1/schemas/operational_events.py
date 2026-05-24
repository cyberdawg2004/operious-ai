"""Transport contracts for canonical operational event reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.events import OperationalEvent, OperationalEventPage
from app.events.lineage import (
    OperationalLineageEdge,
    OperationalLineageUnresolvedReference,
)
from app.events.replay import (
    OperationalReplayFinding,
    OperationalReplayTrace,
)


class OperationalEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    operational_act: str
    substrate: str
    root_event_id: str
    parent_event_id: str | None
    causality_depth: int
    runtime_instance_id: str
    sequence: int
    occurred_at: datetime
    tenant_id: str | None
    principal_id: str | None
    organization_id: str | None
    environment_id: str | None
    tenant_authority_source: str | None
    governance_decision: str | None
    governance_decision_id: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_event(cls, event: OperationalEvent) -> "OperationalEventResponse":
        return cls(
            event_id=str(event.event_id),
            operational_act=event.operational_act.value,
            substrate=event.substrate.value,
            root_event_id=str(event.causality.root_event_id),
            parent_event_id=(
                str(event.causality.parent_event_id)
                if event.causality.parent_event_id is not None
                else None
            ),
            causality_depth=event.causality.depth,
            runtime_instance_id=str(event.chronology.runtime_instance_id),
            sequence=event.chronology.sequence,
            occurred_at=event.chronology.occurred_at,
            tenant_id=event.tenant_id,
            principal_id=event.principal_id,
            organization_id=event.organization_id,
            environment_id=event.environment_id,
            tenant_authority_source=event.tenant_authority_source,
            governance_decision=(
                event.governance_decision.value
                if event.governance_decision is not None
                else None
            ),
            governance_decision_id=event.governance_decision_id,
            metadata=dict(event.metadata),
        )


class OperationalEventPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[OperationalEventResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: OperationalEventPage,
    ) -> "OperationalEventPageResponse":
        return cls(
            items=[
                OperationalEventResponse.from_event(event)
                for event in page.events
            ],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class OperationalLineageEdgeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_event_id: str
    target_event_id: str
    relation: str
    source_substrate: str
    target_substrate: str
    metadata: dict[str, Any]

    @classmethod
    def from_edge(
        cls,
        edge: OperationalLineageEdge,
    ) -> "OperationalLineageEdgeResponse":
        return cls(
            source_event_id=str(edge.source_event_id),
            target_event_id=str(edge.target_event_id),
            relation=edge.relation.value,
            source_substrate=edge.source_substrate.value,
            target_substrate=edge.target_substrate.value,
            metadata=dict(edge.metadata),
        )


class OperationalLineageUnresolvedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_event_id: str
    relation: str
    target_key: str
    metadata: dict[str, Any]

    @classmethod
    def from_reference(
        cls,
        reference: OperationalLineageUnresolvedReference,
    ) -> "OperationalLineageUnresolvedResponse":
        return cls(
            source_event_id=str(reference.source_event_id),
            relation=reference.relation.value,
            target_key=reference.target_key,
            metadata=dict(reference.metadata),
        )


class OperationalReplayFindingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: str
    message: str
    event_id: str | None
    metadata: dict[str, Any]

    @classmethod
    def from_finding(
        cls,
        finding: OperationalReplayFinding,
    ) -> "OperationalReplayFindingResponse":
        return cls(
            code=finding.code.value,
            severity=finding.severity.value,
            message=finding.message,
            event_id=(
                str(finding.event_id)
                if finding.event_id is not None
                else None
            ),
            metadata=dict(finding.metadata),
        )


class OperationalReplayTraceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    root_event_id: str | None
    status: str
    events: list[OperationalEventResponse]
    lineage_edges: list[OperationalLineageEdgeResponse]
    unresolved_lineage: list[OperationalLineageUnresolvedResponse]
    findings: list[OperationalReplayFindingResponse]

    @classmethod
    def from_trace(
        cls,
        trace: OperationalReplayTrace,
    ) -> "OperationalReplayTraceResponse":
        return cls(
            root_event_id=(
                str(trace.root_event_id)
                if trace.root_event_id is not None
                else None
            ),
            status=trace.status.value,
            events=[
                OperationalEventResponse.from_event(event)
                for event in trace.events
            ],
            lineage_edges=[
                OperationalLineageEdgeResponse.from_edge(edge)
                for edge in trace.lineage.edges
            ],
            unresolved_lineage=[
                OperationalLineageUnresolvedResponse.from_reference(reference)
                for reference in trace.lineage.unresolved
            ],
            findings=[
                OperationalReplayFindingResponse.from_finding(finding)
                for finding in trace.findings
            ],
        )


__all__ = [
    "OperationalEventPageResponse",
    "OperationalEventResponse",
    "OperationalLineageEdgeResponse",
    "OperationalLineageUnresolvedResponse",
    "OperationalReplayFindingResponse",
    "OperationalReplayTraceResponse",
]
