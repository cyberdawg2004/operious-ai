"""Backward-compatible capability gate adoption exports."""

from __future__ import annotations

from app.core.capability_gate import (
    CapabilityDenied,
    CapabilityGateOutcome,
    evaluate_capability_gate,
    gate_or_deny,
)
from app.governance.enforcement.runtime import GovernanceRuntime


__all__ = [
    "CapabilityDenied",
    "CapabilityGateOutcome",
    "GovernanceRuntime",
    "evaluate_capability_gate",
    "gate_or_deny",
]
