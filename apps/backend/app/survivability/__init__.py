"""Production survivability shell (P2-E).

Leaf operational-hardening primitives that stabilise the production
surfaces around the constitutional kernel established in
P2-A...P2-D. This sub-package deliberately does NOT mutate ontology:

* No new authority axes (P2-A/B6/B7/B8).
* No new governance class (P2-B).
* No new event kinds (P2-D).
* No new operational acts (P2-B catalog).

What it DOES add:

* :class:`IdempotencyKey` + :class:`IdempotencyRecord` +
  :class:`InMemoryIdempotencyStore` — transport-layer idempotency
  primitive (distinct from the boundary-domain replay registry).
* :class:`ProblemDetails` — RFC 9457 (Problem Details for HTTP APIs)
  Pydantic model + media type constant.
* :class:`ReadinessGate` protocol + :class:`ReadinessRegistry` —
  composition primitive for declaring additional dependency probes
  without touching the existing health service.
* :class:`SurvivabilityHook` — closed vocabulary of named hook
  points production observability can attach to.

Leaf invariants (pinned by
``tests/test_survivability_substrate.py``):

* Imports nothing from sibling orchestration substrates
  (arbitration, session, coordination, boundary, hardening, OI,
  supervisor, agents, middleware, auth, events).
* No adoption / wiring in P2-E — primitives only.
"""

from app.survivability.hooks import SurvivabilityHook
from app.survivability.idempotency import (
    IdempotencyKey,
    IdempotencyPolicy,
    IdempotencyRecord,
    InMemoryIdempotencyStore,
    coerce_idempotency_key,
)
from app.survivability.problem_details import (
    PROBLEM_DETAILS_MEDIA_TYPE,
    ProblemDetails,
    problem_details_response,
)
from app.survivability.readiness import (
    ReadinessGate,
    ReadinessRegistry,
)

__all__ = [
    "IdempotencyKey",
    "IdempotencyPolicy",
    "IdempotencyRecord",
    "InMemoryIdempotencyStore",
    "PROBLEM_DETAILS_MEDIA_TYPE",
    "ProblemDetails",
    "ReadinessGate",
    "ReadinessRegistry",
    "SurvivabilityHook",
    "coerce_idempotency_key",
    "problem_details_response",
]
