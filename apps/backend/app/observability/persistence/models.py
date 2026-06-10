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
    InboundMessageTimelineRecord,
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
class InboundMessageTimelineLookup:
    ingress_id: str | None = None
    external_conversation_id: str | None = None
    session_id: str | None = None
    execution_id: str | None = None
    draft_id: str | None = None
    outbound_send_outbox_id: str | None = None

    def __post_init__(self) -> None:
        populated = self.populated()
        if len(populated) != 1:
            raise ValueError("exactly one inbound timeline lookup key is required")

    def populated(self) -> tuple[tuple[str, str], ...]:
        values = (
            ("ingress_id", self.ingress_id),
            ("external_conversation_id", self.external_conversation_id),
            ("session_id", self.session_id),
            ("execution_id", self.execution_id),
            ("draft_id", self.draft_id),
            ("outbound_send_outbox_id", self.outbound_send_outbox_id),
        )
        return tuple(
            (key, value.strip())
            for key, value in values
            if value is not None and value.strip()
        )

    @property
    def key(self) -> str:
        return self.populated()[0][0]

    @property
    def value(self) -> str:
        return self.populated()[0][1]


@dataclass(frozen=True, slots=True)
class DeadLetterExecutionPage:
    items: tuple[DeadLetterExecutionRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalSLODefinitionPage:
    items: tuple[OperationalSLODefinitionRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalTraceSpanPage:
    items: tuple[OperationalTraceSpanRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class OperationalAlertPage:
    items: tuple[OperationalAlertRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class StuckExecutionAlertPage:
    items: tuple[StuckExecutionAlertRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class InboundNormalizationDeadLetterPage:
    items: tuple[InboundNormalizationDeadLetterRecord, ...]
    total: int
    limit: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class InboundMessageTimelinePage:
    items: tuple[InboundMessageTimelineRecord, ...]
    total: int


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
    "InboundMessageTimelineLookup",
    "InboundMessageTimelinePage",
    "OperationalAlertPage",
    "OperationalMetricsQuery",
    "OperationalSLODefinitionPage",
    "OperationalSLODefinitionQuery",
    "OperationalTraceSpanPage",
    "OperationalTraceSpanQuery",
    "StuckExecutionAlertPage",
    "StuckExecutionAlertQuery",
]
