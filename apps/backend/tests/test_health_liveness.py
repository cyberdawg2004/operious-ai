from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.health_service import HealthService


@pytest.mark.asyncio
async def test_liveness_does_not_probe_external_dependencies() -> None:
    service = HealthService(
        settings=Settings(ENVIRONMENT="test"),
        session_factory_provider=_external_probe_called,
        redis_provider=_external_probe_called,
    )

    report = await service.liveness()

    assert report.check == "live"
    assert report.status == "ok"
    assert report.dependencies == ()
    assert report.queues == {}
    assert report.admission is None


def _external_probe_called() -> None:
    raise AssertionError("liveness must not call external dependency probes")
