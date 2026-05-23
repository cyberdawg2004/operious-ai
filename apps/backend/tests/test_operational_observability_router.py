"""Phase 6-A operational observability router tests."""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_operational_observability_service
from app.main import create_app
from app.observability.persistence import (
    OperationalMetricsSnapshotRecord,
)

_START = datetime(2026, 5, 22, 8, tzinfo=timezone.utc)
_END = datetime(2026, 5, 22, 9, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def observability_client() -> AsyncIterator[tuple[httpx.AsyncClient, "_FakeService"]]:
    app = create_app()
    service = _FakeService()
    app.dependency_overrides[get_operational_observability_service] = (
        _service_override(service)
    )
    app.dependency_overrides[require_tenant_scope] = _tenant_scope_override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client, service


@pytest.mark.asyncio
async def test_metrics_endpoint_uses_request_tenant_scope(
    observability_client: tuple[httpx.AsyncClient, "_FakeService"],
) -> None:
    client, service = observability_client

    response = await client.get(
        "/api/v1/observability/metrics",
        headers=_headers("tenant-acme"),
        params={
            "window_start": _START.isoformat(),
            "window_end": _END.isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-acme"
    assert body["ticket_throughput"] == 7
    assert service.metric_calls == [("tenant-acme", _START, _END)]


def test_observability_router_uses_service_boundary() -> None:
    router_path = (
        Path(__file__).parent.parent
        / "app"
        / "api"
        / "v1"
        / "routers"
        / "observability.py"
    )
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = router_path.read_text(encoding="utf-8")

    assert "app.observability.persistence" not in imported_modules
    assert "app.observability.runtime" not in imported_modules
    assert "PostgresOperationalObservabilityPersistence" not in text
    assert "InMemoryOperationalObservabilityPersistence" not in text
    assert "OperationalObservabilityRuntime" not in text
    assert "get_operational_observability_service" in text


class _FakeService:
    def __init__(self) -> None:
        self.metric_calls: list[tuple[str, datetime, datetime]] = []

    async def read_metrics(
        self,
        *,
        tenant_id: str,
        window_start: datetime,
        window_end: datetime,
    ) -> OperationalMetricsSnapshotRecord:
        self.metric_calls.append((tenant_id, window_start, window_end))
        return OperationalMetricsSnapshotRecord(
            tenant_id=tenant_id,
            window_start=window_start,
            window_end=window_end,
            ticket_throughput=7,
            governance_decision_count=0,
            governance_deny_count=0,
            governance_deny_rate=0.0,
            execution_count=0,
            completed_execution_count=0,
            execution_latency_ms_avg=None,
            execution_latency_ms_p50=None,
            execution_latency_ms_p95=None,
            qa_score_count=0,
            qa_score_average=None,
            qa_score_distribution=(),
            escalation_count=0,
            escalation_rate=0.0,
            dlq_count=0,
        )


def _headers(tenant: str) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-ops"}


def _service_override(
    service: "_FakeService",
) -> Callable[[], Awaitable["_FakeService"]]:
    async def override() -> "_FakeService":
        return service

    return override


async def _tenant_scope_override() -> str:
    return "tenant-acme"
