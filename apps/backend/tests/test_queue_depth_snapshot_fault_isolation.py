"""Break-controls for queue-depth snapshot per-queue fault isolation.

``_collect_queue_depths`` used to abort entirely if any single queue's
depth lookup raised (e.g. a 404 for a queue never created on the
broker), discarding every other queue's already-fetched depth and
logging ``queue_depth_snapshot_failed`` on every periodic run. These
tests prove one queue's failure no longer takes down the rest.
"""

from __future__ import annotations

import logging

import pytest

from app.core.queue_depth import QueueDepthSample, QueueDepthUnavailable
from app.queues import ALL_QUEUES, QUEUE_SEMANTIC_QUARANTINE
from app.workers import celery_app as celery_app_module
from app.workers.celery_app import (
    _collect_queue_depths,  # pyright: ignore[reportPrivateUsage]
)


class _PartiallyFailingProvider:
    backend = "rabbitmq"

    def __init__(self, *, failing_queues: frozenset[str]) -> None:
        self._failing_queues = failing_queues
        self.calls: list[str] = []

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        self.calls.append(queue_name)
        if queue_name in self._failing_queues:
            raise QueueDepthUnavailable("rabbitmq_management_http_error")
        return QueueDepthSample(queue_name=queue_name, depth=len(queue_name))


class _HealthyProvider:
    backend = "rabbitmq"

    async def get_queue_depth(self, queue_name: str) -> QueueDepthSample:
        return QueueDepthSample(queue_name=queue_name, depth=len(queue_name))


@pytest.mark.asyncio
async def test_one_queue_404_does_not_discard_other_queue_depths(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LOAD-BEARING: reproduces the live bug -- semantic_quarantine 404s
    on every run because it's never created on the broker, and used to
    silently discard every other queue's real depth with it.
    """
    caplog.set_level(logging.WARNING)
    provider = _PartiallyFailingProvider(
        failing_queues=frozenset({QUEUE_SEMANTIC_QUARANTINE})
    )
    monkeypatch.setattr(
        celery_app_module, "get_queue_depth_provider", lambda: provider
    )

    depths = await _collect_queue_depths()

    other_queues = [q for q in ALL_QUEUES if q != QUEUE_SEMANTIC_QUARANTINE]
    assert other_queues, "expected at least one other queue to verify isolation"
    for queue_name in other_queues:
        assert depths[queue_name] == len(queue_name)
    assert QUEUE_SEMANTIC_QUARANTINE not in depths
    assert provider.calls == list(ALL_QUEUES)
    assert any(
        record.message == "queue_depth_snapshot_queue_failed"
        and getattr(record, "queue_name", None) == QUEUE_SEMANTIC_QUARANTINE
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_fully_healthy_fetch_returns_every_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-regression: a fully healthy broker still returns the complete
    set of queue depths, unchanged from before fault isolation.
    """
    monkeypatch.setattr(
        celery_app_module, "get_queue_depth_provider", lambda: _HealthyProvider()
    )

    depths = await _collect_queue_depths()

    assert set(depths) == set(ALL_QUEUES)
    for queue_name in ALL_QUEUES:
        assert depths[queue_name] == len(queue_name)


@pytest.mark.asyncio
async def test_failed_queue_is_absent_not_zero_or_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing/404 queue must read as unknown, not as empty (0) or any
    other placeholder value, so it can't feed a false signal into a
    consumer of this snapshot (including admission telemetry).
    """
    provider = _PartiallyFailingProvider(
        failing_queues=frozenset({QUEUE_SEMANTIC_QUARANTINE})
    )
    monkeypatch.setattr(
        celery_app_module, "get_queue_depth_provider", lambda: provider
    )

    depths = await _collect_queue_depths()

    assert depths.get(QUEUE_SEMANTIC_QUARANTINE) is None
    assert all(value >= 0 for value in depths.values())
