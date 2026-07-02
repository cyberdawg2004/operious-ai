"""M4: status_filter enum validation on action-approvals list endpoint.

Invalid status value → 422 (FastAPI schema validation, not a silent empty list).
Valid values → accepted and forwarded to the service layer.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.redis as redis_module
import app.dependencies.services as service_dependencies
import app.main as main_module
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.database import get_db_session
from app.api.v1.schemas.action_approvals import ActionApprovalListResponse
from app.dependencies.services import get_action_approval_service
from app.identity import AuthorityContext
from app.main import create_app

_TENANT_ID = "tenant-status-filter-test"


class _NoopRedis:
    async def ping(self) -> bool:
        return True

    def pipeline(self, *args, **kwargs):  # type: ignore[override]
        return self


class _StubApprovalService:
    """Returns an empty list for any valid call."""

    async def list_by_status(self, **_: object) -> list[object]:
        return []


@pytest_asyncio.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    redis = _NoopRedis()
    monkeypatch.setattr(redis_module, "_redis_client", redis)
    monkeypatch.setattr(main_module, "get_redis_client", lambda: redis)
    monkeypatch.setattr(service_dependencies, "get_redis_client", lambda: redis)
    app = create_app()

    async def _fake_session() -> AsyncIterator[AsyncSession]:
        yield object()  # type: ignore[misc]

    stub = _StubApprovalService()

    app.dependency_overrides[get_db_session] = _fake_session
    app.dependency_overrides[get_action_approval_service] = lambda: stub
    app.dependency_overrides[require_tenant_operations_read] = lambda: AuthorityContext(
        tenant_id=_TENANT_ID,
        capabilities=("tenant.operations.read",),
    )
    app.dependency_overrides[require_tenant_scope] = lambda: _TENANT_ID

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as c:
        yield c


def _headers() -> dict[str, str]:
    return {"X-Tenant-ID": _TENANT_ID}


@pytest.mark.asyncio
async def test_invalid_status_returns_422(client: httpx.AsyncClient) -> None:
    """An unrecognized status value must produce a 422 Unprocessable Entity —
    not a silent 200 with an empty list."""
    response = await client.get(
        "/api/v1/approvals/actions",
        params={"status": "not_a_real_status"},
        headers=_headers(),
    )
    assert response.status_code == 422, (
        f"Expected 422 for invalid status, got {response.status_code}: "
        f"{response.text}"
    )


@pytest.mark.asyncio
async def test_valid_status_pending_accepted(client: httpx.AsyncClient) -> None:
    """status=pending is a valid value and must NOT return 422."""
    response = await client.get(
        "/api/v1/approvals/actions",
        params={"status": "pending"},
        headers=_headers(),
    )
    # 422 would mean the enum rejected it; any non-422 means it was accepted
    assert response.status_code != 422, (
        f"'pending' is a valid status but got 422: {response.text}"
    )


@pytest.mark.asyncio
async def test_valid_status_approved_accepted(client: httpx.AsyncClient) -> None:
    """status=approved is a valid value and must NOT return 422."""
    response = await client.get(
        "/api/v1/approvals/actions",
        params={"status": "approved"},
        headers=_headers(),
    )
    assert response.status_code != 422, (
        f"'approved' is a valid status but got 422: {response.text}"
    )


@pytest.mark.asyncio
async def test_valid_status_denied_accepted(client: httpx.AsyncClient) -> None:
    """status=denied is a valid value and must NOT return 422."""
    response = await client.get(
        "/api/v1/approvals/actions",
        params={"status": "denied"},
        headers=_headers(),
    )
    assert response.status_code != 422, (
        f"'denied' is a valid status but got 422: {response.text}"
    )
