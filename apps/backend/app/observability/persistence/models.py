"""Operational observability query and page value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.observability.enums import OperationalMetricName
from app.observability.identity import (
    OperationalSLODefinitionId,
    OperationalTraceSpanId,
)
from app.observability.persistence.records import (
    DeadLetterExecutionRecord,
    InboundNormalizationDeadLetterRecord,
    OperationalAlertRecord,
    OperationalSLODefinitionRecord,
    OperationalTraceSpanRecord,
    StuckExecutionAlertRecord,
)


@dataclass(frozen=True, slots=True)
class OperationalMetricsQuery:
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        if self.window_end <= self.window_start:
            raise ValueError("window_end must be after window_start")


@dataclass(frozen=True, slots=True)
class DeadLetterExecutionQuery:
    execution_id: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_page(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class OperationalSLODefinitionQuery:
    slo_id: OperationalSLODefinitionId | None = None
    metric_name: OperationalMetricName | None = None
    enabled: bool | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_page(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class OperationalTraceSpanQuery:
    span_id: OperationalTraceSpanId | None = None
    trace_id: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_page(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class StuckExecutionAlertQuery:
    claimed_before_or_at: datetime
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_page(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class InboundNormalizationDeadLetterQuery:
    normalization_status: str | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        _validate_page(self.limit, self.offset)


@dataclass(frozen=True, slots=True)
class DeadLetterExecutionPage:
    items: tuple[DeadLetterExecutionRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalSLODefinitionPage:
    items: tuple[OperationalSLODefinitionRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalTraceSpanPage:
    items: tuple[OperationalTraceSpanRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalAlertPage:
    items: tuple[OperationalAlertRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class StuckExecutionAlertPage:
    items: tuple[StuckExecutionAlertRecord, ...]
    total: int
    offset: int = 0


@dataclass(frozen=True, slots=True)
class InboundNormalizationDeadLetterPage:
    items: tuple[InboundNormalizationDeadLetterRecord, ...]
    total: int
    offset: int = 0


def _validate_page(limit: int, offset: int) -> None:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    if offset < 0:
        raise ValueError("offset must be >= 0")


__all__ = [
    "DeadLetterExecutionPage",
    "DeadLetterExecutionQuery",
    "InboundNormalizationDeadLetterPage",
    "InboundNormalizationDeadLetterQuery",
    "OperationalAlertPage",
    "OperationalMetricsQuery",
    "OperationalSLODefinitionPage",
    "OperationalSLODefinitionQuery",
    "OperationalTraceSpanPage",
    "OperationalTraceSpanQuery",
    "StuckExecutionAlertPage",
    "StuckExecutionAlertQuery",
]
