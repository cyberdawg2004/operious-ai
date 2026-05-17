"""Deterministic coordination-topology evaluator registry.

`CoordinationTopologyRegistry` is the **single** registry of
topology evaluators. The runtime iterates it in sorted-name order
to produce deterministic evaluation outcomes (Sprint L3 replay-
safety requirement).
"""

from app.coordination.topology.registry.registry import (
    CoordinationTopologyRegistry,
)

__all__ = ["CoordinationTopologyRegistry"]
