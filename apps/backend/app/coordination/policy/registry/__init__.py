"""Deterministic coordination-policy registry.

`CoordinationPolicyRegistry` is the **single** registry of
coordination-policy evaluators. The runtime iterates it in
sorted-name order to produce deterministic evaluation outcomes
(Rule 5 — replay safety).
"""

from app.coordination.policy.registry.registry import (
    CoordinationPolicyRegistry,
)

__all__ = ["CoordinationPolicyRegistry"]
