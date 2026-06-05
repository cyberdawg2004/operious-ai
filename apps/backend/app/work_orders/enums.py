"""State vocabulary for generic tenant work orders."""

from __future__ import annotations

from enum import Enum


class WorkOrderState(str, Enum):
    """Explicit state machine for async tenant work orders."""

    CREATED = "created"
    DISPATCHED = "dispatched"
    AWAITING_FULFILLMENT = "awaiting_fulfillment"
    FULFILLED = "fulfilled"
    FAILED = "failed"


__all__ = ["WorkOrderState"]
