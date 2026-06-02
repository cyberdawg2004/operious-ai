"""Admission service persistence tests."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.db.models.admission import AdmissionRecordRow
from app.hardening.admission import (
    AdmissionChannelClass,
    AdmissionGate,
    AdmissionGateThresholds,
    AdmissionOutcome,
    AdmissionReason,
)
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.services.admission_service import AdmissionService


TENANT_ID = "tenant-admission-service"


class _DepthUnavailableRedis:
    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        return {"used_memory": 1, "maxmemory": 0}

    async def llen(self, name: str) -> int:
        del name
        raise RuntimeError("redis unavailable")

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        return []


class _RecordingSession:
    def __init__(self, factory: "_RecordingSessionFactory") -> None:
        self._factory = factory

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback

    def add(self, value: object) -> None:
        assert isinstance(value, AdmissionRecordRow)
        self._factory.rows.append(value)

    async def commit(self) -> None:
        self._factory.commits += 1


class _RecordingSessionFactory:
    def __init__(self) -> None:
        self.rows: list[AdmissionRecordRow] = []
        self.commits = 0

    def __call__(self) -> _RecordingSession:
        return _RecordingSession(self)


def _thresholds() -> AdmissionGateThresholds:
    return AdmissionGateThresholds(
        queue_depth_warn=10,
        queue_depth_reject=20,
        queue_age_warn_seconds=10,
        queue_age_reject_seconds=20,
        redis_memory_pct_warn=70,
        redis_memory_pct_reject=90,
    )


@pytest.mark.parametrize(
    ("channel", "channel_class"),
    (
        ("email", AdmissionChannelClass.ASYNC_TICKET),
        ("batch_ingest", AdmissionChannelClass.BATCH),
        ("internal_execution", AdmissionChannelClass.INTERNAL_EXECUTION),
    ),
)
@pytest.mark.asyncio
async def test_telemetry_failure_defers_and_persists_for_processing_channels(
    channel: str,
    channel_class: AdmissionChannelClass,
) -> None:
    session_factory = _RecordingSessionFactory()
    service = AdmissionService(
        gate=AdmissionGate(
            redis_client=_DepthUnavailableRedis(),
            thresholds=_thresholds(),
        ),
        session_factory=session_factory,  # type: ignore[arg-type]
    )

    decision = await service.evaluate_and_persist(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel=channel,
    )

    assert decision.outcome is AdmissionOutcome.DEFER
    assert decision.reason is AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING
    assert decision.telemetry_unavailable is True
    assert decision.channel_class is channel_class
    assert session_factory.commits == 1
    row = session_factory.rows[0]
    assert row.outcome == AdmissionOutcome.DEFER.value
    assert row.reason == AdmissionReason.TELEMETRY_UNAVAILABLE_PROCESSING.value
    assert row.telemetry_unavailable is True
    assert row.channel_class == channel_class.value
    assert row.queue_depth_available is False
    assert row.unavailable_reasons == [
        f"queue_depth_unavailable:{QUEUE_DIAGNOSTIC_NORMAL}"
    ]
