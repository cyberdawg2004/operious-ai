"""Operator quota operations router tests."""

from __future__ import annotations

import ast
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from starlette.requests import Request

from app.agents.runtime.quota_runtime import QuotaStatus
from app.dependencies.authority import (
    ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED,
    require_operator_authority,
    require_tenant_scope,
)
from app.dependencies.services import get_quota_operations_service
from app.identity import AuthorityContext
from app.main import create_app
from app.services.quota_operations_service import (
    ProviderQuotaRecord,
    ProviderQuotaRecordPage,
    QuotaTenantScopeError,
)

_NOW = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def quota_client() -> AsyncIterator[
    tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"]
]:
    app = create_app()
    service = _FakeQuotaOperationsService()
    app.dependency_overrides[get_quota_operations_service] = (
        _service_override(service)
    )
    app.dependency_overrides[require_tenant_scope] = _tenant_scope_override
    app.dependency_overrides[require_operator_authority] = (
        _operator_authority_override
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client, service


@pytest.mark.asyncio
async def test_operator_can_set_force_open(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, service = quota_client

    response = await client.post(
        "/api/v1/quota/circuit/tenant-acme/anthropic",
        json={"circuit_state": "force_open", "reason": "provider incident"},
    )

    assert response.status_code == 200
    assert response.json()["operator_circuit_state"] == "force_open"
    assert service.override_calls == [
        (
            "tenant-acme",
            "tenant-acme",
            "anthropic",
            "force_open",
            "operator-principal",
            "provider incident",
        )
    ]


@pytest.mark.asyncio
async def test_operator_can_set_force_close(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, _service = quota_client

    response = await client.post(
        "/api/v1/quota/circuit/tenant-acme/anthropic",
        json={"circuit_state": "force_close", "reason": "manual recovery"},
    )

    assert response.status_code == 200
    assert response.json()["operator_circuit_state"] == "force_close"


@pytest.mark.asyncio
async def test_operator_can_clear_override(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, _service = quota_client

    response = await client.post(
        "/api/v1/quota/circuit/tenant-acme/anthropic",
        json={"circuit_state": None, "reason": "return to automatic mode"},
    )

    assert response.status_code == 200
    assert response.json()["operator_circuit_state"] is None


@pytest.mark.asyncio
async def test_tenant_cannot_set_circuit_for_other_tenant(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, service = quota_client

    response = await client.post(
        "/api/v1/quota/circuit/tenant-other/anthropic",
        json={"circuit_state": "force_open", "reason": "wrong tenant"},
    )

    assert response.status_code == 403
    assert "quota_tenant_scope_forbidden" in response.text
    assert service.override_calls == []


@pytest.mark.asyncio
async def test_quota_status_returns_correct_counters(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, service = quota_client

    response = await client.get(
        "/api/v1/quota/status/tenant-acme/anthropic/claude-sonnet",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requests_per_minute_count"] == 12
    assert body["requests_per_hour_count"] == 120
    assert body["operator_circuit_state"] == "force_open"
    assert service.status_calls == [
        ("tenant-acme", "tenant-acme", "anthropic", "claude-sonnet")
    ]


@pytest.mark.asyncio
async def test_quota_records_scoped_to_tenant(
    quota_client: tuple[httpx.AsyncClient, "_FakeQuotaOperationsService"],
) -> None:
    client, service = quota_client

    response = await client.get("/api/v1/quota/records/tenant-acme")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["tenant_id"] == "tenant-acme"
    assert service.records_calls == [("tenant-acme", "tenant-acme", 25, 0)]


@pytest.mark.asyncio
async def test_non_operator_authority_is_rejected() -> None:
    request = _request(
        AuthorityContext.from_raw(
            tenant_id="tenant-acme",
            principal_id="tenant-user",
            capabilities=frozenset({"session:open"}),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await require_operator_authority(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": ERROR_CODE_OPERATOR_AUTHORITY_REQUIRED
    }


def test_quota_operations_router_uses_service_boundary() -> None:
    router_path = (
        Path(__file__).parent.parent
        / "app"
        / "api"
        / "v1"
        / "routers"
        / "quota_operations.py"
    )
    tree = ast.parse(router_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    text = router_path.read_text(encoding="utf-8")

    assert "app.agents.runtime.quota_runtime" not in imported_modules
    assert "TenantQuotaRuntime" not in text
    assert "get_quota_runtime" not in text
    assert "get_quota_operations_service" in text


class _FakeQuotaOperationsService:
    def __init__(self) -> None:
        self.override_calls: list[
            tuple[str, str, str, str | None, str, str]
        ] = []
        self.status_calls: list[tuple[str, str, str, str]] = []
        self.records_calls: list[tuple[str, str, int, int]] = []

    async def set_operator_override(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        provider: str,
        circuit_state: str | None,
        set_by: str,
        reason: str,
    ) -> ProviderQuotaRecord:
        if tenant_id != expected_tenant_id:
            raise QuotaTenantScopeError("scope mismatch")
        self.override_calls.append(
            (
                tenant_id,
                expected_tenant_id,
                provider,
                circuit_state,
                set_by,
                reason,
            )
        )
        return _record(
            tenant_id=tenant_id,
            provider=provider,
            circuit_state=(
                circuit_state
                if circuit_state in ("force_open", "force_close")
                else None
            ),
            reason=reason,
            set_by=set_by,
        )

    async def get_quota_status(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        provider: str,
        model: str,
    ) -> QuotaStatus:
        if tenant_id != expected_tenant_id:
            raise QuotaTenantScopeError("scope mismatch")
        self.status_calls.append(
            (tenant_id, expected_tenant_id, provider, model)
        )
        return QuotaStatus(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
            requests_per_minute_count=12,
            requests_per_minute_limit=60,
            requests_per_hour_count=120,
            requests_per_hour_limit=1_000,
            tokens_per_minute_count=None,
            tokens_per_minute_limit=100_000,
            operator_circuit_state="force_open",
            redis_available=True,
        )

    async def list_quota_records(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int,
        offset: int,
    ) -> ProviderQuotaRecordPage:
        if tenant_id != expected_tenant_id:
            raise QuotaTenantScopeError("scope mismatch")
        self.records_calls.append(
            (tenant_id, expected_tenant_id, limit, offset)
        )
        return ProviderQuotaRecordPage(
            items=(
                _record(
                    tenant_id="tenant-acme",
                    provider="anthropic",
                    circuit_state="force_open",
                    reason="provider incident",
                    set_by="operator-principal",
                ),
            ),
            total=1,
            offset=offset,
        )


def _record(
    *,
    tenant_id: str,
    provider: str,
    circuit_state: str | None,
    reason: str,
    set_by: str,
) -> ProviderQuotaRecord:
    return ProviderQuotaRecord(
        id=f"provider_quota:{tenant_id}:{provider}:operator_override",
        tenant_id=tenant_id,
        provider=provider,
        model="*",
        quota_type="operator_override",
        window_start=_NOW,
        window_count=0,
        quota_limit=0,
        is_exhausted=False,
        operator_circuit_state=cast(
            Literal["force_open", "force_close"] | None,
            circuit_state,
        ),
        operator_set_by=set_by,
        operator_set_at=_NOW,
        operator_reason=reason,
        created_at=_NOW,
        updated_at=_NOW,
        metadata={},
    )


def _service_override(
    service: "_FakeQuotaOperationsService",
) -> Callable[[], Awaitable["_FakeQuotaOperationsService"]]:
    async def override() -> "_FakeQuotaOperationsService":
        return service

    return override


async def _tenant_scope_override() -> str:
    return "tenant-acme"


async def _operator_authority_override() -> AuthorityContext:
    return AuthorityContext.from_raw(
        tenant_id="tenant-acme",
        principal_id="operator-principal",
        capabilities=frozenset({"operator"}),
    )


def _request(authority: AuthorityContext) -> Request:
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "headers": [],
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "state": {},
        }
    )
    request.state.authority = authority
    return request
