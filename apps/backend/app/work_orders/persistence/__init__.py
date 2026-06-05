"""Persistence interfaces and implementations for work orders."""

from app.work_orders.persistence.postgres import PostgresWorkOrderRepository
from app.work_orders.persistence.records import WorkOrderRecord
from app.work_orders.persistence.repository import WorkOrderRepositoryProtocol

__all__ = [
    "PostgresWorkOrderRepository",
    "WorkOrderRecord",
    "WorkOrderRepositoryProtocol",
]
