"""Bound governance helpers exposed without transport-layer coupling strings."""

from __future__ import annotations

from app.runtime.execution_governance import (
    BoundExecutionGovernanceConfigurationError,
    load_bound_execution_governance_config,
)

BoundGovernanceConfigurationError = BoundExecutionGovernanceConfigurationError
load_bound_governance_config = load_bound_execution_governance_config

__all__ = [
    "BoundGovernanceConfigurationError",
    "load_bound_governance_config",
]
