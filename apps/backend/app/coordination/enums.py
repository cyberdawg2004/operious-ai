"""Coordination enum vocabulary — pinned wire-format values.

Four typed vocabularies the coordination substrate speaks in. All
string-shaped values are `StrEnum` (transparent JSON round-trips,
deterministic persistence); the priority enum is `IntEnum` so
comparisons / sorting follow numeric ordering.

Wire-format discipline: every value below is a stable string / int
that the persistence layer stores verbatim. Renaming a value is a
breaking change to every previously persisted coordination record;
the `tests/test_coordination_invariants.py` catalogue pins these
values so accidental drift fails at import time.

The vocabulary deliberately avoids:

* hidden orchestration states (e.g. ``ROUTING``, ``ENQUEUED``) — the
  substrate is sequential and deterministic; there is no async fanout
  to enumerate intermediate states for.
* broker / queue semantics (``ACKED``, ``REQUEUED``, ``DEAD_LETTER``)
  — coordination is not a messaging bus.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class CoordinationStatus(StrEnum):
    """Terminal lifecycle status of a coordination envelope.

    The envelope is created INSIDE `CoordinationRuntime.dispatch()`
    and lands in exactly one terminal status before being persisted.
    There is no asynchronous transition — the status is decided in
    the same call that produces the envelope.

    PENDING       — sentinel only; produced when callers construct
                    envelopes outside the runtime for tests / replay
                    reconstruction. Never written by `dispatch()`.
    DISPATCHED    — governance allowed the dispatch; the envelope was
                    persisted and is the authoritative record of the
                    message.
    DEGRADED      — governance returned a non-blocking restriction
                    (DEGRADE / REDACT); the dispatch proceeded with the
                    restrictions attached, the envelope is persisted.
    DENIED        — governance produced a blocking decision (DENY /
                    REQUIRE_APPROVAL / ESCALATE); the envelope is
                    persisted as an audit-grade record of the rejected
                    attempt but no recipient delivery occurs.
    POLICY_DENIED   — coordination policy (topology authorisation
                      rules) produced a blocking decision (DENY /
                      ESCALATE) BEFORE governance ran. The envelope
                      is persisted as an audit-grade record of the
                      policy-rejected attempt. **Distinct semantic**
                      from `DENIED`: `POLICY_DENIED` is a topology-
                      authorisation-policy failure, `DENIED` is an
                      operational-governance refusal (Sprint L2
                      Rule 2).
    TOPOLOGY_DENIED — coordination *topology* (structural authority
                      — declared edges, paths, boundaries, chain
                      depth) produced a blocking decision (DENIED /
                      ESCALATED / DEPTH_EXCEEDED / BOUNDARY_VIOLATION)
                      BEFORE coordination policy ran. The envelope
                      is persisted as an audit-grade record of the
                      topology-structurally-rejected attempt.
                      **Distinct semantic** from `POLICY_DENIED` and
                      `DENIED`: topology is the *structural* layer;
                      policy is the *rule* layer; governance is the
                      *operational* layer (Sprint L3 final directive).
    FAILED          — the dispatch itself failed (validation,
                      persistence error, or a substrate framework
                      error in topology / policy / governance). The
                      envelope MAY still be persisted as a failure
                      record, depending on the failure stage.
    """

    PENDING = "pending"
    DISPATCHED = "dispatched"
    DEGRADED = "degraded"
    DENIED = "denied"
    POLICY_DENIED = "policy_denied"
    TOPOLOGY_DENIED = "topology_denied"
    FAILED = "failed"


class CoordinationMessageType(StrEnum):
    """Semantic classification of a coordination message.

    Closed set — adding a new value is a deliberate vocabulary
    change. Downstream consumers (replay, audit) MUST treat unknown
    values fail-safe.

    REQUEST       — solicit a downstream action; expects a logically
                    paired RESPONSE (the substrate does not enforce
                    pairing; it merely names the intent).
    RESPONSE      — reply to a prior REQUEST; the runtime preserves
                    causality via `in_reply_to` on the message.
    NOTIFICATION  — informational; no response expected.
    HANDOFF       — explicit transfer of operational authority from
                    sender to recipient (e.g. retriever → planner).
    SIGNAL        — control-plane event (heartbeat, cancellation
                    indication, state-machine pulse). Distinct from
                    NOTIFICATION because signals are typically
                    fire-and-forget and consumed by the recipient's
                    runtime, not its agent body.
    """

    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    HANDOFF = "handoff"
    SIGNAL = "signal"


class CoordinationPriority(IntEnum):
    """Operational priority hint for a coordination message.

    Priority is an *audit-grade* signal — the substrate does NOT
    reorder envelopes by priority (ordering is sequence-deterministic;
    see `CoordinationEnvelope.sequence`). Recipients and supervisors
    may inspect priority to triage; the substrate preserves the value
    verbatim across persistence and replay.

    Numeric values follow the governance `ViolationSeverity` pattern
    (LOW=10 .. CRITICAL=40) so cross-substrate dashboards can apply a
    single ordinal scale.
    """

    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


class CoordinationDirection(StrEnum):
    """Direction-of-flow classification for a coordination message.

    The direction describes the *logical* flow between participants;
    every dispatch still goes THROUGH the coordination runtime
    (Rule 1 — no direct agent-to-agent calls). The runtime uses this
    field for routing inspectability, audit dashboards, and
    governance-context construction; it is NOT consulted to decide
    delivery semantics.

    AGENT_TO_AGENT      — peer coordination between two registered
                          agents (mediated by the runtime).
    AGENT_TO_SUPERVISOR — an agent surfaces a finding / status to the
                          supervisor runtime.
    SUPERVISOR_TO_AGENT — a supervisor recommendation routed to a
                          registered agent. The supervisor remains
                          read-only (Rule 7) — the agent decides
                          whether to act.
    RUNTIME_TO_AGENT    — orchestration-layer dispatch to an agent
                          (e.g. initial activation, parent-runtime
                          handoff).
    AGENT_TO_RUNTIME    — agent surfaces a structured event back to
                          an orchestration runtime.
    SYSTEM_BROADCAST    — substrate-level announcement (no specific
                          recipient identity beyond the recipient
                          scope on the recipient value object).
    """

    AGENT_TO_AGENT = "agent_to_agent"
    AGENT_TO_SUPERVISOR = "agent_to_supervisor"
    SUPERVISOR_TO_AGENT = "supervisor_to_agent"
    RUNTIME_TO_AGENT = "runtime_to_agent"
    AGENT_TO_RUNTIME = "agent_to_runtime"
    SYSTEM_BROADCAST = "system_broadcast"


__all__ = [
    "CoordinationStatus",
    "CoordinationMessageType",
    "CoordinationPriority",
    "CoordinationDirection",
]
