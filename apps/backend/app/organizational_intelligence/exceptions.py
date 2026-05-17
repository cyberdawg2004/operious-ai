"""Organizational-intelligence exception hierarchy.

Public runtime methods NEVER raise. The classes below are the
internal discriminators that runtimes use to populate envelope
errors.

The discipline: any attempt to **bypass the human approval flow**
raises `IntelligenceAuthorityError` — this is the central rule
of Sprint O.
"""

from __future__ import annotations


class IntelligenceError(Exception):
    """Base class for organizational-intelligence failures."""


class IntelligenceConfigurationError(IntelligenceError):
    """Composition-time error (registry / dependency wiring)."""


class IntelligenceValidationError(IntelligenceError):
    """Caller-supplied request violates the substrate contract."""


class IntelligenceNotFoundError(IntelligenceError):
    """Read for an unknown artifact / record."""


class IntelligenceAuthorityError(IntelligenceError):
    """Operation would bypass the human approval flow.

    Raised when:

    * A caller attempts to set ``status=APPROVED`` directly
      without an `ApprovalRecord`.
    * A caller attempts to make a non-approved artifact
      retrieval-eligible.
    * A caller attempts to auto-promote a SOP / pattern /
      recommendation through any path other than the approval
      gate.

    This exception is the **central invariant** of Sprint O.
    """


class IntelligenceLineageError(IntelligenceError):
    """Lineage invariant violation (cycle, missing ancestor, drift)."""


class IntelligencePersistenceError(IntelligenceError):
    """Persistence-backend rejected a write or read."""


class IntelligenceApprovalError(IntelligenceError):
    """Approval-flow invariant violation.

    Examples:

    * Approving an already-rejected artifact.
    * Re-approving an APPROVED artifact without superseding.
    * Approving with a non-human authority kind.
    """


__all__ = [
    "IntelligenceApprovalError",
    "IntelligenceAuthorityError",
    "IntelligenceConfigurationError",
    "IntelligenceError",
    "IntelligenceLineageError",
    "IntelligenceNotFoundError",
    "IntelligencePersistenceError",
    "IntelligenceValidationError",
]
