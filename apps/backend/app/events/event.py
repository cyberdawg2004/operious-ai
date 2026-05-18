"""Apex :class:`OperationalEvent` — six-axis institutional state
transition (P2-D).

Constitutional invariants
─────────────────────────
* Frozen + slotted: zero in-place mutation possible.
* No mutation-style methods: no ``with_*``, no ``update``, no
  ``replace`` on the type. Construction is the only legitimate way
  to obtain an instance. (``dataclasses.replace(event, ...)`` works
  on any frozen dataclass — that is a callable from outside the
  type, not a method, and the substrate-leaf invariant test pins
  that NO module under ``app/`` calls it on
  :class:`OperationalEvent`.)
* All six constitutional axes are required: act / substrate /
  authority / causality / chronology / legality.
* The authority axis carries the resolved
  ``tenant_authority_source`` from
  :class:`app.identity.AuthorityResolution` so audit / replay can
  reconstruct which surface won.
* ``metadata`` is an opaque ``Mapping[str, Any]`` for substrate-
  specific structured payload; it carries forward the canonical
  ordering established by Phase 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.events.causality import EventCausality
from app.events.chronology import EventChronology
from app.events.identity import EventId
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    """A constitutionally meaningful operational state transition.

    Attributes:
        event_id: Deterministic UUIDv5 identifier (see
            :func:`app.events.derive_event_id`).
        operational_act: WHAT happened — the operational act being
            recorded.
        substrate: WHICH organizational substrate emitted it.
        causality: Parent + root + depth envelope.
        chronology: Runtime + monotonic sequence + advisory wall-
            clock.
        tenant_id: AUTHORITY axis — tenant scope at emission time.
        principal_id: AUTHORITY axis — verified principal, if any.
        organization_id: AUTHORITY axis — organization scope.
        environment_id: AUTHORITY axis — environment (peer of
            tenant, per Wedge A decision).
        tenant_authority_source: AUTHORITY axis — which surface
            produced the tenant attribution
            (:class:`app.identity.AuthoritySource` string).
        governance_decision: LEGALITY axis —
            :class:`app.governance.Decision` value if the act was
            evaluated through governance; ``None`` if no evaluation
            occurred (e.g. genesis events).
        governance_decision_id: LEGALITY axis — stable identifier of
            the governance decision for replay correlation.
        metadata: Opaque, substrate-specific structured payload.
    """

    event_id: EventId
    operational_act: OperationalAct
    substrate: OperationalSubstrate
    causality: EventCausality
    chronology: EventChronology

    # AUTHORITY axis (all defaulted to None for genesis / anonymous events).
    tenant_id: str | None = None
    principal_id: str | None = None
    organization_id: str | None = None
    environment_id: str | None = None
    tenant_authority_source: str | None = None

    # LEGALITY axis (None means the event did not flow through
    # governance evaluation; reserved for genesis / replay events).
    governance_decision: Decision | None = None
    governance_decision_id: str | None = None

    # Opaque payload.
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["OperationalEvent"]
