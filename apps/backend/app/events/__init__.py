"""Institutional event fabric (P2-D).

This sub-package is the constitutional substrate primitive for
**operational state transitions**. It does NOT model "infrastructure
chatter"; it models the six-axis representation of a
constitutionally meaningful operational act:

    1. WHAT       — :class:`OperationalAct`
    2. AUTHORITY  — tenant / principal / organization / environment +
                    source attribution (from
                    :class:`AuthorityResolution`)
    3. CAUSALITY  — :class:`EventCausality` (parent_event_id +
                    root_event_id + depth)
    4. CHRONOLOGY — :class:`EventChronology`
                    (runtime_instance_id + monotonic sequence +
                    advisory wall-clock)
    5. LEGALITY   — governance decision + decision_id
    6. SUBSTRATE  — :class:`OperationalSubstrate`

Constitutional invariants (enforced by tests under
``tests/test_operational_event_fabric.py``)
─────────────────────────────────────────
* **Append-oriented.** No method on :class:`OperationalEvent` returns
  a "mutated copy"; there is no ``.with_*``, ``.update``,
  ``.replace``, or ``dataclasses.replace`` reference on the type.
* **Immutable.** Every primitive in this sub-package is
  ``frozen=True, slots=True``.
* **Causality-linked.** Every event declares a
  :class:`EventCausality`; a root event has ``parent_event_id=None``
  and ``depth=0``; a child event has both non-None and ``depth>=1``.
  Mismatch raises at construction.
* **Replay-safe.** :func:`derive_event_id` is a pure UUIDv5
  derivation; identical seeds produce identical ids. NUL-bounded
  optional projection (see :func:`app.identity.project_optional_str`)
  prevents ``None != ""`` collapses.
* **Authority-attributed.** Every event carries the resolved
  ``tenant_id``, ``principal_id``, ``organization_id``,
  ``environment_id``, AND ``tenant_authority_source`` so audit /
  replay can reconstruct which authority surface produced each
  attribution (carries forward the B6/B7/P2-C provenance discipline).

Substrate position
──────────────────
* Leaf below :mod:`app.identity` and :mod:`app.governance.capability`.
* Does not import from any sibling orchestration substrate
  (arbitration, session, coordination, boundary, hardening, OI).
* No orchestration wiring in P2-D — adoption is a later wedge under
  explicit direction.
"""

from app.events.causality import EventCausality
from app.events.chronology import EventChronology
from app.events.event import OperationalEvent
from app.events.exceptions import (
    EventCausalityError,
    EventChronologyError,
    EventFabricError,
)
from app.events.identity import EventId, derive_event_id
from app.events.substrates import OperationalSubstrate

__all__ = [
    "EventCausality",
    "EventCausalityError",
    "EventChronology",
    "EventChronologyError",
    "EventFabricError",
    "EventId",
    "OperationalEvent",
    "OperationalSubstrate",
    "derive_event_id",
]
