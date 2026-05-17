"""Deterministic coordination registry.

`CoordinationRegistry` is populated at composition time with the
participants the deployment trusts as senders / recipients.
Iteration is **explicitly sorted by participant id** so introspection
is deterministic across processes and replays.
"""

from app.coordination.registry.registry import CoordinationRegistry

__all__ = ["CoordinationRegistry"]
