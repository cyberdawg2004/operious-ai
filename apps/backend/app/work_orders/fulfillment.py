"""Fulfillment-event consumer for async tenant work orders."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from app.work_orders.enums import WorkOrderState
from app.work_orders.identity import WorkOrderId
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol
from app.work_orders.state_machine import is_terminal

FulfillmentReportedStatus = Literal["fulfilled", "failed"]


def _empty_metadata() -> Mapping[str, Any]:
    return {}


class WorkOrderFulfillmentOutcome(StrEnum):
    """Outcomes from consuming one recorded fulfillment status event."""

    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED_NON_AWAITING = "ignored_non_awaiting"
    UNCORRELATED = "uncorrelated"


@dataclass(frozen=True, slots=True)
class WorkOrderFulfillmentSignal:
    """Tenant-scoped fulfillment status derived from a recorded ingress event."""

    tenant_id: str
    provider_work_order_id: str
    reported_status: FulfillmentReportedStatus
    source_ingress_id: str
    source_event_id: str | None = None
    provider_status: str | None = None
    provider_error: str | None = None
    received_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class WorkOrderFulfillmentConsumptionResult:
    """Result of attempting to apply a fulfillment status event."""

    outcome: WorkOrderFulfillmentOutcome
    work_order_id: WorkOrderId | None
    from_state: WorkOrderState | None
    to_state: WorkOrderState | None


class WorkOrderFulfillmentConsumer:
    """Apply tenant-reported fulfillment callbacks to awaiting work orders."""

    def __init__(
        self,
        *,
        repository: WorkOrderRepositoryProtocol,
        now: datetime | None = None,
    ) -> None:
        self._repository = repository
        self._now = now

    async def consume(
        self,
        signal: WorkOrderFulfillmentSignal,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderFulfillmentConsumptionResult:
        _assert_tenant(signal.tenant_id, expected_tenant_id)
        target_state = _target_state(signal.reported_status)
        work_order = await (
            self._repository.get_work_order_by_provider_work_order_id(
                provider_work_order_id=signal.provider_work_order_id,
                expected_tenant_id=expected_tenant_id,
            )
        )
        if work_order is None:
            return WorkOrderFulfillmentConsumptionResult(
                outcome=WorkOrderFulfillmentOutcome.UNCORRELATED,
                work_order_id=None,
                from_state=None,
                to_state=None,
            )
        if work_order.state is target_state and is_terminal(work_order.state):
            return WorkOrderFulfillmentConsumptionResult(
                outcome=WorkOrderFulfillmentOutcome.DUPLICATE,
                work_order_id=work_order.work_order_id,
                from_state=work_order.state,
                to_state=work_order.state,
            )
        if work_order.state is not WorkOrderState.AWAITING_FULFILLMENT:
            return WorkOrderFulfillmentConsumptionResult(
                outcome=WorkOrderFulfillmentOutcome.IGNORED_NON_AWAITING,
                work_order_id=work_order.work_order_id,
                from_state=work_order.state,
                to_state=work_order.state,
            )
        transitioned = await self._repository.transition_work_order(
            work_order.work_order_id,
            to_state=target_state,
            transitioned_at=signal.received_at or self._transition_time(),
            expected_tenant_id=expected_tenant_id,
            provider_work_order_id=signal.provider_work_order_id,
            provider_status=signal.provider_status or signal.reported_status,
            metadata={
                "phase": "tenant_fulfillment_callback",
                "source_ingress_id": signal.source_ingress_id,
                "source_event_id": signal.source_event_id,
                "reported_status": signal.reported_status,
                "provider_error": signal.provider_error,
                **dict(signal.metadata),
            },
        )
        return WorkOrderFulfillmentConsumptionResult(
            outcome=WorkOrderFulfillmentOutcome.APPLIED,
            work_order_id=transitioned.work_order_id,
            from_state=work_order.state,
            to_state=transitioned.state,
        )

    def _transition_time(self) -> datetime:
        return self._now or datetime.now(timezone.utc)


def _target_state(status: FulfillmentReportedStatus) -> WorkOrderState:
    if status == "fulfilled":
        return WorkOrderState.FULFILLED
    return WorkOrderState.FAILED


def _assert_tenant(signal_tenant_id: str, expected_tenant_id: str) -> None:
    if signal_tenant_id != expected_tenant_id:
        raise ValueError("signal tenant_id does not match expected_tenant_id")


__all__ = [
    "FulfillmentReportedStatus",
    "WorkOrderFulfillmentConsumptionResult",
    "WorkOrderFulfillmentConsumer",
    "WorkOrderFulfillmentOutcome",
    "WorkOrderFulfillmentSignal",
]
