"""Phase 6-E operational event read endpoint tests."""

from __future__ import annotations

import ast
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_operational_event_service
from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventPage,
    OperationalReplayTrace,
    OperationalSubstrate,
)
from app.events.lineage import OperationalLineageGraph
from app.events.replay import OperationalReplayStatus
from app.governance.capability.acts import OperationalAct
from app.main import create_app

_EVENT_ID = EventId("00000000-0000-0000-0000-00000000e601")
_ROOT_ID = EventId("00000000-0000-0000-0000-00000000e601")
_RUNTIME_ID = uuid.UUID("00000000-0000-0000-0000-00000000e602")
_NOW = datetime(2026, 5, 24, 1, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def operational_event_client() -> tuple[httpx.AsyncClient, "_FakeService"]:
    app = create_app()
    service = _FakeService()
    app.dependency_overrides[get_operational_event_service] = (
        _service_override(service)
    )
    app.dependency_overrides[require_tenant_scope] = _tenant_scope_override
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client, service  # type: ignore[misc]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_operational_events_are_tenant_scoped(
    operational_event_client: tuple[httpx.AsyncClient, "_FakeService"],
) -> None:
    client, service = operational_event_client

    response = await client.get(
        "/api/v1/operational-events",
        headers=_headers(),
        params={"limit": 25, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["event_id"] == str(_EVENT_ID)
    assert body["items"][0]["operational_act"] == "governance:decide"
    assert service.list_calls == [("tenant-acme", 25, 0)]


@pytest.mark.asyncio
async def test_operational_replay_endpoint_returns_canonical_events(
    operational_event_client: tuple[httpx.AsyncClient, "_FakeService"],
) -> None:
    client, service = operational_event_client

    response = await client.get(
        "/api/v1/operational-events/replay",
        headers=_headers(),
        params={"governance_decision_id": "decision-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["root_event_id"] == str(_ROOT_ID)
    assert body["status"] == "complete"
    assert body["events"][0]["substrate"] == "governance"
    assert service.replay_calls == [("tenant-acme", "decision-1")]


def test_operational_events_router_uses_service_boundary() -> None:
    router_path = (
        Path(__file__).parent.parent
        / "app"
        / "api"
        / "v1"
        / "routers"
        / "operational_events.py"
    )
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = router_path.read_text(encoding="utf-8")

    assert "app.events" not in imported_modules
    assert "app.events.runtime" not in imported_modules
    assert "PostgresOperationalEventPersistence" not in text
    assert "OperationalEventRuntime" not in text
    assert "get_operational_event_service" in text


class _FakeService:
    def __init__(self) -> None:
        self.list_calls: list[tuple[str, int, int]] = []
        self.replay_calls: list[tuple[str, str | None]] = []

    async def list_events(
        self,
        *,
        tenant_id: str,
        event_id: str | None = None,
        operational_act: str | None = None,
        substrate: str | None = None,
        root_event_id: str | None = None,
        parent_event_id: str | None = None,
        governance_decision_id: str | None = None,
        occurred_after_or_at: datetime | None = None,
        occurred_before_or_at: datetime | None = None,
        limit: int,
        offset: int,
    ) -> OperationalEventPage:
        self.list_calls.append((tenant_id, limit, offset))
        return OperationalEventPage(
            events=(_event(),),
            total=1,
            limit=limit,
            offset=offset,
        )

    async def load_replay_trace(
        self,
        *,
        tenant_id: str,
        event_id: str | None = None,
        root_event_id: str | None = None,
        operational_act: str | None = None,
        substrate: str | None = None,
        governance_decision_id: str | None = None,
        occurred_after_or_at: datetime | None = None,
        occurred_before_or_at: datetime | None = None,
        limit: int,
        offset: int,
    ) -> OperationalReplayTrace:
        self.replay_calls.append((tenant_id, governance_decision_id))
        event = _event()
        return OperationalReplayTrace(
            root_event_id=event.causality.root_event_id,
            events=(event,),
            lineage=OperationalLineageGraph(events=(event,)),
            findings=(),
            status=OperationalReplayStatus.COMPLETE,
        )


def _event() -> OperationalEvent:
    return OperationalEvent(
        event_id=_EVENT_ID,
        operational_act=OperationalAct.GOVERNANCE_DECIDE,
        substrate=OperationalSubstrate.GOVERNANCE,
        causality=EventCausality(
            root_event_id=_ROOT_ID,
            parent_event_id=None,
            depth=0,
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME_ID,
            sequence=1,
            occurred_at=_NOW,
        ),
        tenant_id="tenant-acme",
        principal_id="principal-ops",
        tenant_authority_source="header",
        governance_decision_id="decision-1",
        metadata={"session_id": "session-1"},
    )


def _headers() -> dict[str, str]:
    return {"X-Tenant-ID": "tenant-acme", "X-Principal-ID": "principal-ops"}


def _service_override(
    service: "_FakeService",
) -> Callable[[], Awaitable["_FakeService"]]:
    async def override() -> "_FakeService":
        return service

    return override


async def _tenant_scope_override() -> str:
    return "tenant-acme"
