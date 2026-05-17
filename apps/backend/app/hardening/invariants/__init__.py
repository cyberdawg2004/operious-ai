"""Pinned hardening-substrate invariants.

These collections are imported by tests to pin the substrate's
public surface area. Renaming any of these is a breaking change
that the invariant tests will refuse to allow silently.
"""

from app.hardening.enums import (
    HardeningFindingKind,
    HardeningSeverity,
    HardeningStatus,
    HardeningTraceKind,
    IntegrityStatus,
    ReplayStatus,
    SubstrateName,
    SurvivabilityStatus,
)


PINNED_FINDING_KINDS = frozenset(
    member.value for member in HardeningFindingKind
)

PINNED_SEVERITIES = frozenset(
    member.value for member in HardeningSeverity
)

PINNED_TRACE_KINDS = frozenset(
    member.value for member in HardeningTraceKind
)

PINNED_SUBSTRATE_NAMES = frozenset(
    member.value for member in SubstrateName
)

PINNED_INTEGRITY_STATUSES = frozenset(
    member.value for member in IntegrityStatus
)

PINNED_REPLAY_STATUSES = frozenset(
    member.value for member in ReplayStatus
)

PINNED_SURVIVABILITY_STATUSES = frozenset(
    member.value for member in SurvivabilityStatus
)

PINNED_HARDENING_STATUSES = frozenset(
    member.value for member in HardeningStatus
)


# Forbidden words inside hardening implementation modules.
# The runtime hardening must NEVER call out for self-healing,
# auto-recovery, autonomous failover, etc. These tokens are
# pinned in tests/test_hardening_invariants.py.
FORBIDDEN_AUTO_MUTATION_TOKENS = frozenset(
    [
        "auto_heal",
        "auto_recover",
        "autonomous_failover",
        "self_modify",
        "auto_route",
        "auto_dispatch",
        "auto_orchestrate",
        "auto_repair",
        "self_correct",
    ]
)


__all__ = [
    "FORBIDDEN_AUTO_MUTATION_TOKENS",
    "PINNED_FINDING_KINDS",
    "PINNED_HARDENING_STATUSES",
    "PINNED_INTEGRITY_STATUSES",
    "PINNED_REPLAY_STATUSES",
    "PINNED_SEVERITIES",
    "PINNED_SUBSTRATE_NAMES",
    "PINNED_SURVIVABILITY_STATUSES",
    "PINNED_TRACE_KINDS",
]
