"""Generic work-order dispatch substrate."""

from app.work_orders.enums import WorkOrderState
from app.work_orders.identity import (
    WorkOrderId,
    as_work_order_id,
    derive_work_order_id,
)

__all__ = [
    "WorkOrderId",
    "WorkOrderState",
    "as_work_order_id",
    "derive_work_order_id",
]
