"""SOP failure-pattern detection over DLQ and admission records."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from sqlalchemy import String, and_, cast as sa_cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.admission import AdmissionRecordRow
from app.events import (
    EventCausality,
    EventChronology,
    OperationalEvent,
    OperationalSubstrate,
    derive_event_id,
)
from app.events.persistence import (
    OperationalEventPersistenceProtocol,
    PostgresOperationalEventPersistence,
)
from app.execution.db.models import ExecutionRow
from app.governance.capability.acts import OperationalAct
from app.runtime.db.models import DeadLetterTaskRow, SOPFailurePatternRow

DLQ_WINDOW_HOURS: int = 24
DLQ_THRESHOLD: int = 3

_DIAGNOSTIC_TASK_NAME = "execute_diagnostic_agent"
_UNKNOWN_DIAGNOSTIC_CATEGORY = "unknown_diagnostic"
_FAILURE_PATTERN_NAMESPACE = uuid.UUID("a8b67337-169c-5f76-9260-a0d3190d8c7d")
_TRIGGER_ID_LIMIT = 10


@dataclass(frozen=True, slots=True)
class FailurePattern:
    tenant_id: str
    category: str
    failure_count: int
    pattern_source: str
    window_start: datetime
    window_end: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class RecordedFailurePattern:
    pattern_id: uuid.UUID
    inserted: bool


class FailurePatternDetectionRuntime:
    """
    Queries DLQ and admission records to detect systemic failure
    patterns that indicate SOP gaps.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        event_persistence: OperationalEventPersistenceProtocol | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._event_persistence = (
            event_persistence
            if event_persistence is not None
            else PostgresOperationalEventPersistence(session)
        )
        self._now = now or _utcnow

    async def detect_dlq_patterns(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        window_hours: int = DLQ_WINDOW_HOURS,
        threshold: int = DLQ_THRESHOLD,
    ) -> list[FailurePattern]:
        """
        Query diagnostic-agent DLQ records, grouping by execution
        diagnostic category when available.
        """

        window_start, window_end = _validated_window(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            window_hours=window_hours,
            threshold=threshold,
            now=self._now(),
        )
        category_expr = func.coalesce(
            ExecutionRow.diagnostic_category,
            _UNKNOWN_DIAGNOSTIC_CATEGORY,
        )
        count_expr = func.count(DeadLetterTaskRow.dead_letter_task_id)
        trigger_ids_expr = func.array_agg(
            sa_cast(DeadLetterTaskRow.dead_letter_task_id, String)
        )
        stmt = (
            select(
                category_expr.label("category"),
                count_expr.label("failure_count"),
                trigger_ids_expr.label("trigger_dlq_ids"),
                func.min(DeadLetterTaskRow.created_at).label("window_start"),
                func.max(DeadLetterTaskRow.created_at).label("window_end"),
            )
            .select_from(DeadLetterTaskRow)
            .outerjoin(
                ExecutionRow,
                and_(
                    DeadLetterTaskRow.execution_id == ExecutionRow.execution_id,
                    ExecutionRow.tenant_id == expected_tenant_id,
                ),
            )
            .where(
                DeadLetterTaskRow.tenant_id == expected_tenant_id,
                DeadLetterTaskRow.task_name == _DIAGNOSTIC_TASK_NAME,
                DeadLetterTaskRow.created_at >= window_start,
                DeadLetterTaskRow.created_at <= window_end,
            )
            .group_by(category_expr)
            .having(count_expr >= threshold)
            .order_by(category_expr)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            FailurePattern(
                tenant_id=expected_tenant_id,
                category=str(row[0] or _UNKNOWN_DIAGNOSTIC_CATEGORY),
                failure_count=int(row[1]),
                pattern_source="dlq",
                window_start=_coerce_aware(cast(datetime, row[3])),
                window_end=_coerce_aware(cast(datetime, row[4])),
                metadata={
                    "trigger_dlq_ids": _bounded_trigger_ids(row[2]),
                },
            )
            for row in rows
        ]

    async def detect_admission_patterns(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        window_hours: int = DLQ_WINDOW_HOURS,
        threshold: int = DLQ_THRESHOLD,
    ) -> list[FailurePattern]:
        """Query DEFER/REJECT admission records grouped by channel."""

        window_start, window_end = _validated_window(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            window_hours=window_hours,
            threshold=threshold,
            now=self._now(),
        )
        count_expr = func.count(AdmissionRecordRow.decision_id)
        trigger_ids_expr = func.array_agg(
            sa_cast(AdmissionRecordRow.decision_id, String)
        )
        stmt = (
            select(
                AdmissionRecordRow.channel,
                count_expr.label("failure_count"),
                trigger_ids_expr.label("trigger_admission_ids"),
                func.min(AdmissionRecordRow.evaluated_at).label("window_start"),
                func.max(AdmissionRecordRow.evaluated_at).label("window_end"),
            )
            .where(
                AdmissionRecordRow.tenant_id == expected_tenant_id,
                AdmissionRecordRow.outcome.in_(("DEFER", "REJECT")),
                AdmissionRecordRow.evaluated_at >= window_start,
                AdmissionRecordRow.evaluated_at <= window_end,
            )
            .group_by(AdmissionRecordRow.channel)
            .having(count_expr >= threshold)
            .order_by(AdmissionRecordRow.channel)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            FailurePattern(
                tenant_id=expected_tenant_id,
                category=f"admission_{_category_part(cast(str | None, row[0]))}",
                failure_count=int(row[1]),
                pattern_source="admission",
                window_start=_coerce_aware(cast(datetime, row[3])),
                window_end=_coerce_aware(cast(datetime, row[4])),
                metadata={
                    "trigger_admission_ids": _bounded_trigger_ids(row[2]),
                },
            )
            for row in rows
        ]

    async def record_detected_pattern(
        self,
        *,
        pattern: FailurePattern,
        expected_tenant_id: str,
        window_hours: int,
        threshold: int,
        metadata: Mapping[str, Any] | None = None,
    ) -> RecordedFailurePattern:
        """Persist one detected pattern and append its operational event."""

        if pattern.tenant_id != expected_tenant_id:
            raise ValueError("pattern tenant_id does not match expected_tenant_id")
        if window_hours < 1:
            raise ValueError("window_hours must be >= 1")
        if threshold < 1:
            raise ValueError("threshold must be >= 1")

        pattern_id = derive_sop_failure_pattern_id(
            tenant_id=pattern.tenant_id,
            category=pattern.category,
            window_start=pattern.window_start,
        )
        pattern_metadata = {
            "_schema_version": "1",
            "tenant_id": pattern.tenant_id,
            "category": pattern.category,
            "pattern_source": pattern.pattern_source,
            "failure_count": pattern.failure_count,
            "window_start": pattern.window_start.isoformat(),
            "window_end": pattern.window_end.isoformat(),
            **dict(pattern.metadata),
            **dict(metadata or {}),
        }
        stmt = (
            pg_insert(SOPFailurePatternRow)
            .values(
                pattern_id=pattern_id,
                tenant_id=pattern.tenant_id,
                pattern_source=pattern.pattern_source,
                category=pattern.category,
                failure_count=pattern.failure_count,
                window_hours=window_hours,
                window_start=pattern.window_start,
                window_end=pattern.window_end,
                threshold_used=threshold,
                status="detected",
                metadata_json=pattern_metadata,
            )
            .on_conflict_do_nothing(
                index_elements=[SOPFailurePatternRow.pattern_id]
            )
        )
        result = await self._session.execute(stmt)
        inserted = getattr(result, "rowcount", 0) == 1
        if inserted:
            await self._event_persistence.append_event(
                _sop_failure_pattern_detected_event(
                    pattern_id=pattern_id,
                    pattern=pattern,
                    threshold=threshold,
                    window_hours=window_hours,
                )
            )
        return RecordedFailurePattern(pattern_id=pattern_id, inserted=inserted)

    async def mark_pattern_proposed(
        self,
        *,
        pattern_id: uuid.UUID,
        expected_tenant_id: str,
        proposal_id: str | uuid.UUID,
    ) -> bool:
        """Attach the SOP proposal id once proposal creation succeeds."""

        parsed_proposal_id = _parse_uuid(proposal_id)
        stmt = select(SOPFailurePatternRow).where(
            SOPFailurePatternRow.pattern_id == pattern_id,
            SOPFailurePatternRow.tenant_id == expected_tenant_id,
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        row.sop_proposal_id = parsed_proposal_id
        row.status = "proposed"
        metadata = dict(row.metadata_json)
        metadata["sop_proposal_id"] = str(parsed_proposal_id)
        row.metadata_json = metadata
        await self._session.flush()
        return True


def derive_sop_failure_pattern_id(
    *,
    tenant_id: str,
    category: str,
    window_start: datetime,
) -> uuid.UUID:
    seed = "|".join(
        [
            tenant_id,
            category,
            _coerce_aware(window_start).isoformat(),
        ]
    )
    return uuid.uuid5(_FAILURE_PATTERN_NAMESPACE, seed)


def _sop_failure_pattern_detected_event(
    *,
    pattern_id: uuid.UUID,
    pattern: FailurePattern,
    threshold: int,
    window_hours: int,
) -> OperationalEvent:
    runtime_instance_id = uuid.uuid5(
        _FAILURE_PATTERN_NAMESPACE,
        f"{pattern_id}:runtime",
    )
    sequence = 0
    event_id = derive_event_id(
        operational_act=OperationalAct.SOP_FAILURE_PATTERN_DETECTED.value,
        substrate=OperationalSubstrate.OI_SOP.value,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        tenant_id=pattern.tenant_id,
        parent_event_id=None,
    )
    metadata: dict[str, Any] = {
        "_schema_version": "1",
        "pattern_id": str(pattern_id),
        "tenant_id": pattern.tenant_id,
        "category": pattern.category,
        "failure_count": pattern.failure_count,
        "pattern_source": pattern.pattern_source,
        "window_hours": window_hours,
        "window_start": pattern.window_start.isoformat(),
        "window_end": pattern.window_end.isoformat(),
        "threshold_used": threshold,
        **dict(pattern.metadata),
    }
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.SOP_FAILURE_PATTERN_DETECTED,
        substrate=OperationalSubstrate.OI_SOP,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            occurred_at=pattern.window_end,
        ),
        tenant_id=pattern.tenant_id,
        metadata=metadata,
    )


def _validated_window(
    *,
    tenant_id: str,
    expected_tenant_id: str,
    window_hours: int,
    threshold: int,
    now: datetime,
) -> tuple[datetime, datetime]:
    if tenant_id != expected_tenant_id:
        raise ValueError("tenant_id does not match expected_tenant_id")
    if window_hours < 1:
        raise ValueError("window_hours must be >= 1")
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    window_end = _coerce_aware(now)
    return window_end - timedelta(hours=window_hours), window_end


def _category_part(value: str | None) -> str:
    candidate = (value or "unknown").strip()
    return candidate or "unknown"


def _parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


def _bounded_trigger_ids(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        values = tuple(cast(Sequence[object], value))
    else:
        values = (value,)
    return [str(item) for item in values if item is not None][:_TRIGGER_ID_LIMIT]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "DLQ_THRESHOLD",
    "DLQ_WINDOW_HOURS",
    "FailurePattern",
    "FailurePatternDetectionRuntime",
    "RecordedFailurePattern",
    "derive_sop_failure_pattern_id",
]
