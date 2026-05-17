"""Wire-format pinning for session substrate enums."""

from __future__ import annotations

from app.session.enums import (
    SessionContinuityMode,
    SessionCorrelationKind,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionReconstructionStatus,
    SessionScope,
)


_LIFECYCLE_WIRE: dict[SessionLifecyclePhase, str] = {
    SessionLifecyclePhase.INITIATED: "initiated",
    SessionLifecyclePhase.ACTIVE: "active",
    SessionLifecyclePhase.DORMANT: "dormant",
    SessionLifecyclePhase.TERMINATED: "terminated",
    SessionLifecyclePhase.ARCHIVED: "archived",
}

_SCOPE_WIRE: dict[SessionScope, str] = {
    SessionScope.TENANT: "tenant",
    SessionScope.PRINCIPAL: "principal",
    SessionScope.OPERATIONAL_DOMAIN: "operational_domain",
    SessionScope.GLOBAL: "global",
}

_EVENT_KIND_WIRE: dict[SessionEventKind, str] = {
    SessionEventKind.SESSION_OPENED: "session_opened",
    SessionEventKind.CONTEXT_ATTACHED: "context_attached",
    SessionEventKind.CORRELATION_RECORDED: "correlation_recorded",
    SessionEventKind.LINEAGE_LINKED: "lineage_linked",
    SessionEventKind.LIFECYCLE_RECLASSIFIED: "lifecycle_reclassified",
    SessionEventKind.DORMANCY_RECORDED: "dormancy_recorded",
    SessionEventKind.RESUMPTION_RECORDED: "resumption_recorded",
    SessionEventKind.TERMINATION_RECORDED: "termination_recorded",
    SessionEventKind.ARCHIVAL_RECORDED: "archival_recorded",
    SessionEventKind.OPERATIONAL_OBSERVATION: "operational_observation",
}

_CONTINUITY_MODE_WIRE: dict[SessionContinuityMode, str] = {
    SessionContinuityMode.SYNCHRONOUS: "synchronous",
    SessionContinuityMode.DEFERRED: "deferred",
    SessionContinuityMode.RECONSTRUCTED: "reconstructed",
}

_RECONSTRUCTION_STATUS_WIRE: dict[
    SessionReconstructionStatus, str
] = {
    SessionReconstructionStatus.PRISTINE: "pristine",
    SessionReconstructionStatus.PARTIAL: "partial",
    SessionReconstructionStatus.DRIFT_DETECTED: "drift_detected",
    SessionReconstructionStatus.NOT_FOUND: "not_found",
    SessionReconstructionStatus.ERROR: "error",
}

_CORRELATION_KIND_WIRE: dict[SessionCorrelationKind, str] = {
    SessionCorrelationKind.GOVERNANCE: "governance",
    SessionCorrelationKind.TOPOLOGY: "topology",
    SessionCorrelationKind.POLICY: "policy",
    SessionCorrelationKind.COORDINATION: "coordination",
    SessionCorrelationKind.AGENT_EXECUTION: "agent_execution",
    SessionCorrelationKind.SUPERVISOR: "supervisor",
    SessionCorrelationKind.ARBITRATION: "arbitration",
    SessionCorrelationKind.BOUNDARY: "boundary",
    SessionCorrelationKind.MEMORY: "memory",
    SessionCorrelationKind.EXTERNAL: "external",
    SessionCorrelationKind.GENERIC: "generic",
}


def test_lifecycle_wire_pinned() -> None:
    for member, expected in _LIFECYCLE_WIRE.items():
        assert member.value == expected
    assert set(SessionLifecyclePhase) == set(_LIFECYCLE_WIRE)


def test_scope_wire_pinned() -> None:
    for member, expected in _SCOPE_WIRE.items():
        assert member.value == expected
    assert set(SessionScope) == set(_SCOPE_WIRE)


def test_event_kind_wire_pinned() -> None:
    for member, expected in _EVENT_KIND_WIRE.items():
        assert member.value == expected
    assert set(SessionEventKind) == set(_EVENT_KIND_WIRE)


def test_continuity_mode_wire_pinned() -> None:
    for member, expected in _CONTINUITY_MODE_WIRE.items():
        assert member.value == expected
    assert set(SessionContinuityMode) == set(_CONTINUITY_MODE_WIRE)


def test_reconstruction_status_wire_pinned() -> None:
    for member, expected in _RECONSTRUCTION_STATUS_WIRE.items():
        assert member.value == expected
    assert set(SessionReconstructionStatus) == set(
        _RECONSTRUCTION_STATUS_WIRE
    )


def test_correlation_kind_wire_pinned() -> None:
    for member, expected in _CORRELATION_KIND_WIRE.items():
        assert member.value == expected
    assert set(SessionCorrelationKind) == set(
        _CORRELATION_KIND_WIRE
    )
