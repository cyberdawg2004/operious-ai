"""Session substrate enum vocabulary — pinned wire-format values.

These vocabularies are CLASSIFICATIONS of operational continuity,
not directives. None of them encode "what to do next"; every
member describes "what the substrate observed about continuity".

Wire-format discipline: every value below is pinned. Renaming a
value is a breaking change to every previously persisted session
record. `tests/test_session_invariants.py` pins the catalogue so
accidental drift fails at import time.

Critical architectural rule (Sprint N):

* The Session Runtime is a **continuity ledger**, not a workflow
  engine. The vocabularies below describe WHAT the substrate
  observed about a session's lineage / timeline; they NEVER
  instruct WHAT to execute next.
* Lifecycle phases are CLASSIFICATIONS, not state-machine
  transitions. A reclassification only annotates the timeline; it
  never schedules, dispatches, retries, or re-routes.
"""

from __future__ import annotations

from enum import StrEnum


class SessionLifecyclePhase(StrEnum):
    """Coarse classification of a session's continuity state.

    INITIATED  — session opened; no events appended yet.
    ACTIVE     — session is currently accumulating timeline events.
    DORMANT    — session has been explicitly classified inactive
                  (paused / idle / awaiting external continuation).
    TERMINATED — session has been explicitly closed; no further
                  events are accepted.
    ARCHIVED   — terminal cold-storage classification; equivalent
                  to TERMINATED but separated to distinguish
                  cold-archive bookkeeping from live operational
                  history.

    All transitions are EXPLICIT — initiated by an inbound
    `record_lifecycle()` call. The runtime NEVER auto-transitions.
    """

    INITIATED = "initiated"
    ACTIVE = "active"
    DORMANT = "dormant"
    TERMINATED = "terminated"
    ARCHIVED = "archived"


class SessionScope(StrEnum):
    """Authority/scoping classification of a session.

    TENANT             — bound to a tenant identity.
    PRINCIPAL          — bound to a specific principal (user/agent).
    OPERATIONAL_DOMAIN — bound to a non-tenant operational domain
                          (e.g. integration boundary).
    GLOBAL             — substrate-internal; no scoping principal.
    """

    TENANT = "tenant"
    PRINCIPAL = "principal"
    OPERATIONAL_DOMAIN = "operational_domain"
    GLOBAL = "global"


class SessionEventKind(StrEnum):
    """Closed vocabulary for timeline-event classification.

    Every event the substrate ever appends to a timeline maps to
    one of these classifications. Adding a value is a deliberate
    vocabulary change — invariant tests pin the catalogue.

    SESSION_OPENED            — the bootstrap event of every
                                  session.
    CONTEXT_ATTACHED          — `SessionContext` bound to the
                                  session.
    CORRELATION_RECORDED      — cross-substrate correlation
                                  observation.
    LINEAGE_LINKED            — explicit ancestry annotation
                                  (parent / sibling session).
    LIFECYCLE_RECLASSIFIED    — explicit lifecycle phase change.
    DORMANCY_RECORDED         — session marked DORMANT.
    RESUMPTION_RECORDED       — session lifted out of DORMANT.
    TERMINATION_RECORDED      — session marked TERMINATED.
    ARCHIVAL_RECORDED         — session marked ARCHIVED.
    OPERATIONAL_OBSERVATION   — generic externally-supplied
                                  observation (substrate-agnostic
                                  audit annotation).
    """

    SESSION_OPENED = "session_opened"
    CONTEXT_ATTACHED = "context_attached"
    CORRELATION_RECORDED = "correlation_recorded"
    LINEAGE_LINKED = "lineage_linked"
    LIFECYCLE_RECLASSIFIED = "lifecycle_reclassified"
    DORMANCY_RECORDED = "dormancy_recorded"
    RESUMPTION_RECORDED = "resumption_recorded"
    TERMINATION_RECORDED = "termination_recorded"
    ARCHIVAL_RECORDED = "archival_recorded"
    OPERATIONAL_OBSERVATION = "operational_observation"


class SessionContinuityMode(StrEnum):
    """How a timeline event entered the timeline.

    SYNCHRONOUS   — appended live, while the originating
                     observation was being made.
    DEFERRED      — appended after the fact (out-of-band ingest).
    RECONSTRUCTED — emitted by the reconstruction pipeline; never
                     written to persistence.
    """

    SYNCHRONOUS = "synchronous"
    DEFERRED = "deferred"
    RECONSTRUCTED = "reconstructed"


class SessionReconstructionStatus(StrEnum):
    """Outcome classification of a reconstruction call.

    PRISTINE       — timeline reconstructed byte-identically
                      from persisted records; no gaps or drift.
    PARTIAL        — reconstruction succeeded but the requested
                      time window is incomplete (events outside
                      the bound were dropped).
    DRIFT_DETECTED — persistence returned events whose canonical
                      sequence does not match the recorded order
                      (deterministic ordering invariant violated;
                      the substrate refuses to silently re-order).
    NOT_FOUND      — the requested session is unknown.
    ERROR          — framework-level failure during reconstruction.
    """

    PRISTINE = "pristine"
    PARTIAL = "partial"
    DRIFT_DETECTED = "drift_detected"
    NOT_FOUND = "not_found"
    ERROR = "error"


class SessionCorrelationKind(StrEnum):
    """Which sibling-substrate artifact this correlation references.

    These are STRING tags only — the session substrate never
    imports the typed identifiers from sibling runtimes.

    GOVERNANCE      — a governance evaluation id.
    TOPOLOGY        — a coordination-topology evaluation id.
    POLICY          — a coordination-policy evaluation id.
    COORDINATION    — a coordination-dispatch envelope id.
    AGENT_EXECUTION — an agent-runtime execution id.
    SUPERVISOR      — a supervisor-runtime evaluation id.
    ARBITRATION     — an operational-arbitration evaluation id.
    BOUNDARY        — a boundary-runtime ingress / egress id.
    MEMORY          — a memory-runtime artifact id.
    EXTERNAL        — an external (non-Operious) reference.
    GENERIC         — caller-defined / unclassified.
    """

    GOVERNANCE = "governance"
    TOPOLOGY = "topology"
    POLICY = "policy"
    COORDINATION = "coordination"
    AGENT_EXECUTION = "agent_execution"
    SUPERVISOR = "supervisor"
    ARBITRATION = "arbitration"
    BOUNDARY = "boundary"
    MEMORY = "memory"
    EXTERNAL = "external"
    GENERIC = "generic"


__all__ = [
    "SessionContinuityMode",
    "SessionCorrelationKind",
    "SessionEventKind",
    "SessionLifecyclePhase",
    "SessionReconstructionStatus",
    "SessionScope",
]
