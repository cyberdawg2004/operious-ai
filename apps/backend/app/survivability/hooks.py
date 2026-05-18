"""Survivability hook-point vocabulary (P2-E).

A closed catalog of named hook points production observability can
attach to. The catalog is intentionally narrow: each value names ONE
operationally meaningful inflection point in the request lifecycle
where metrics / logs / traces can plug in.

Values follow ``<phase>:<event>`` snake_case (mirrors
:class:`app.governance.capability.acts.OperationalAct` discipline).

This module is a VOCABULARY — it does not implement the hook
mechanism. Adoption is deferred: future wedges may introduce a
registry or rely on existing
:mod:`app.observability` infrastructure to dispatch on the names.
"""

from __future__ import annotations

from enum import StrEnum


class SurvivabilityHook(StrEnum):
    """Closed catalog of named production-observability hook points."""

    # Request lifecycle (HTTP transport layer).
    REQUEST_RECEIVED = "request:received"
    REQUEST_AUTHORIZED = "request:authorized"
    REQUEST_REJECTED = "request:rejected"
    REQUEST_COMPLETED = "request:completed"

    # Idempotency lifecycle.
    IDEMPOTENCY_HIT = "idempotency:hit"
    IDEMPOTENCY_FIRST = "idempotency:first"
    IDEMPOTENCY_CONFLICT = "idempotency:conflict"

    # Readiness lifecycle.
    READINESS_DEGRADED = "readiness:degraded"
    READINESS_RECOVERED = "readiness:recovered"

    # Failure surfacing.
    PROBLEM_EMITTED = "problem:emitted"


__all__ = ["SurvivabilityHook"]
