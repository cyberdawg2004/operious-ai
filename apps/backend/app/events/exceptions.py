"""Event fabric exceptions (P2-D).

Distinct from :class:`app.identity.IdentityError` (malformed identity
primitive) and :class:`app.auth.errors.AuthenticationError` (provider
refusal). These exceptions describe the failure of an event to satisfy
its own constitutional invariants.
"""

from __future__ import annotations


class EventFabricError(Exception):
    """Apex base for every event-fabric refusal."""


class EventCausalityError(EventFabricError):
    """Raised when a :class:`EventCausality` violates its root /
    depth invariants (e.g. a root with depth>0, or a child with
    depth==0)."""


class EventChronologyError(EventFabricError):
    """Raised when a :class:`EventChronology` carries an invalid
    monotonic sequence (e.g. negative)."""


class EventPersistenceError(EventFabricError):
    """Raised when durable event authority refuses an append."""


__all__ = [
    "EventCausalityError",
    "EventChronologyError",
    "EventFabricError",
    "EventPersistenceError",
]
