"""Router-level authorization proof for the least-privilege demo recorder.

These tests bind a deterministic authority onto request state exactly where the
production authority middleware does.  They intentionally do not override a
route authorization dependency: the real capability and tenant-scope gates
must run before the in-memory read-service spies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request, Response

from app.api.v1.routers.session import router as session_router
from app.api.v1.routers.supervisor import router as supervisor_router
from app.dependencies.services import (
    get_session_read_service,
    get_supervisor_inbox_service,
)
from app.identity import AuthorityContext
from app.services.supervisor_inbox_service import SupervisorInboxPage
from app.session.identity import SessionId
from app.session.models.timeline import SessionTimeline

_TENANT = "northstar-clueso-demo"
_SESSION_ID = str(uuid4())


class _SessionReadSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def get_timeline(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> SessionTimeline:
        self.calls += 1
        assert expected_tenant_id == _TENANT
        return SessionTimeline(
            session_id=SessionId(session_id), events=(), head_sequence=-1
        )


class _SupervisorReadSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def list_inspections(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        status: str,
        session_id: str | None,
        limit: int,
        offset: int,
    ) -> SupervisorInboxPage:
        del status, session_id
        self.calls += 1
        assert tenant_id == _TENANT
        assert expected_tenant_id == _TENANT
        return SupervisorInboxPage(items=(), total=0, limit=limit, offset=offset)


def _app(
    authority: AuthorityContext,
    *,
    session_service: _SessionReadSpy,
    supervisor_service: _SupervisorReadSpy,
) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _bind_authority(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.authority = authority
        return await call_next(request)

    async def _session_service() -> _SessionReadSpy:
        return session_service

    async def _supervisor_service() -> _SupervisorReadSpy:
        return supervisor_service

    app.dependency_overrides[get_session_read_service] = _session_service
    app.dependency_overrides[get_supervisor_inbox_service] = _supervisor_service
    app.include_router(session_router, prefix="/session")
    app.include_router(supervisor_router, prefix="/supervisor")
    return app


async def _get(client: httpx.AsyncClient, path: str) -> httpx.Response:
    """Bound each in-process route request so regressions cannot hang tests."""

    return await asyncio.wait_for(client.get(path), timeout=5)


@pytest.mark.asyncio
async def test_recorder_can_read_timeline_and_supervisor_inbox() -> None:
    recorder = AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="clueso-demo@operious.com",
        capabilities=frozenset(
            {"tenant.operations.read", "tenant.supervisor.read"}
        ),
    )
    session_service = _SessionReadSpy()
    supervisor_service = _SupervisorReadSpy()
    transport = httpx.ASGITransport(
        app=_app(
            recorder,
            session_service=session_service,
            supervisor_service=supervisor_service,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        timeline = await _get(client, f"/session/{_SESSION_ID}/timeline")
        supervisor = await _get(client, "/supervisor/inspections")

    assert timeline.status_code == 200
    assert timeline.json() == {"events": [], "total": 0}
    assert supervisor.status_code == 200
    assert supervisor.json() == {"items": [], "total": 0, "offset": 0, "limit": 25}
    assert session_service.calls == 1
    assert supervisor_service.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capabilities", "path", "service_name"),
    [
        (frozenset(), f"/session/{_SESSION_ID}/timeline", "session"),
        (frozenset({"tenant.operations.read"}), "/supervisor/inspections", "supervisor"),
    ],
)
async def test_missing_recorder_read_capability_fails_closed(
    capabilities: frozenset[str], path: str, service_name: str
) -> None:
    session_service = _SessionReadSpy()
    supervisor_service = _SupervisorReadSpy()
    authority = AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="clueso-demo@operious.com",
        capabilities=capabilities,
    )
    transport = httpx.ASGITransport(
        app=_app(
            authority,
            session_service=session_service,
            supervisor_service=supervisor_service,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await _get(client, path)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "capability_required"
    if service_name == "session":
        assert session_service.calls == 0
    else:
        assert supervisor_service.calls == 0
