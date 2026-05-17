"""Storage-agnostic query / page shapes for the agent persistence layer.

Mirrors the shape of `app.governance.persistence.models` — same
discipline, separate module so the agent persistence layer doesn't
import from the governance persistence layer (replay tools may want
one without the other).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


@dataclass(frozen=True, slots=True)
class ExecutionQuery:
    """Query parameters for retrieving agent execution records.

    Every field is optional; consumers compose narrow queries by
    combining them. `limit` + `offset` provide forward-only pagination
    suitable for any backend.
    """

    execution_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    agent_id: str | None = None
    parent_execution_id: str | None = None
    final_state: str | None = None
    runtime_instance_id: str | None = None
    limit: int = 100
    offset: int = 0


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RecordPage(Generic[T]):
    """One page of records returned by a query."""

    items: tuple[T, ...] = field(default_factory=tuple)
    total: int = -1
    offset: int = 0


__all__ = ["ExecutionQuery", "RecordPage"]
