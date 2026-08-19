"""Router-level break-control: a case-bound action approval that fails to
complete its linked case must surface as a clean 4xx, not an unhandled
500 (which a browser reports as an opaque "NetworkError").

Confirmed live: approving a real case-bound action whose reply failed
grounding revalidation raised CaseApprovalRuntimeError from inside
ActionApprovalService._complete_bound_case_if_any (Fix B's completion
hook) -- a type the router's exception handling didn't know about, so
it propagated unhandled instead of becoming the same clean 4xx the
case_approvals router already returns for the identical denial.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest
from fastapi import FastAPI, Request, Response

from app.api.v1.routers.action_approvals import router as action_approvals_router
from app.approvals.exceptions import CaseApprovalRuntimeError
from app.dependencies.authority import (
    TENANT_ACTIONS_APPROVE_CAPABILITY,
)
from app.dependencies.services import get_action_approval_service
from app.identity import AuthorityContext

_TENANT = "tenant-action-approvals-router"


class _CaseCompletionFailsService:
    def __init__(self) -> None:
        self.approve_calls = 0
        self.deny_calls = 0

    async def approve(self, **kwargs: object) -> object:
        self.approve_calls += 1
        raise CaseApprovalRuntimeError(
            "revised SME reply failed resolution governance (deny); "
            "escalate the case"
        )

    async def deny(self, **kwargs: object) -> object:
        self.deny_calls += 1
        raise CaseApprovalRuntimeError(
            "revised SME reply failed resolution governance (deny); "
            "escalate the case"
        )


def _test_app(
    service: object,
    *,
    authority: AuthorityContext | None = None,
) -> FastAPI:
    app = FastAPI()
    bound_authority = authority or AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="operator-approve",
        capabilities=frozenset({TENANT_ACTIONS_APPROVE_CAPABILITY}),
    )

    @app.middleware("http")
    async def _bind_authority(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.authority = bound_authority
        return await call_next(request)

    async def _service_override() -> object:
        return service

    app.dependency_overrides[get_action_approval_service] = _service_override
    app.include_router(action_approvals_router, prefix="/approvals/actions")
    return app


@pytest.mark.asyncio
async def test_approve_surfaces_case_completion_failure_as_clean_400() -> None:
    service = _CaseCompletionFailsService()
    transport = httpx.ASGITransport(app=_test_app(service))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/actions/action-1/approve", json={"note": "looks good"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "case_completion_failed"}
    assert service.approve_calls == 1


@pytest.mark.asyncio
async def test_deny_surfaces_case_completion_failure_as_clean_400() -> None:
    service = _CaseCompletionFailsService()
    transport = httpx.ASGITransport(app=_test_app(service))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/actions/action-1/deny", json={"reason": "no longer needed"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "case_completion_failed"}
    assert service.deny_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload", "call_attribute"),
    [
        ("approve", {"note": "looks good"}, "approve_calls"),
        ("deny", {"reason": "no longer needed"}, "deny_calls"),
    ],
)
async def test_recorder_cannot_invoke_action_approval_routes(
    path: str,
    payload: dict[str, str],
    call_attribute: str,
) -> None:
    """The real approval dependency rejects the recorder before the service."""

    service = _CaseCompletionFailsService()
    recorder = AuthorityContext.from_raw(
        tenant_id="northstar-clueso-demo",
        # The identity's stable principal axis is the recorder address. Roles
        # are resolved upstream into this capability-only authority context.
        principal_id="clueso-demo@operious.com",
        capabilities=frozenset(
            {"tenant.operations.read", "tenant.supervisor.read"}
        ),
    )
    transport = httpx.ASGITransport(app=_test_app(service, authority=recorder))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/approvals/actions/action-1/{path}", json=payload
        )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "capability_required",
        "capability": TENANT_ACTIONS_APPROVE_CAPABILITY,
    }
    assert getattr(service, call_attribute) == 0


@pytest.mark.asyncio
async def test_matching_recorder_email_and_tenant_do_not_substitute_for_approval() -> None:
    service = _CaseCompletionFailsService()
    authority = AuthorityContext.from_raw(
        tenant_id="northstar-clueso-demo",
        principal_id="clueso-demo@operious.com",
        capabilities=frozenset(),
    )
    transport = httpx.ASGITransport(app=_test_app(service, authority=authority))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/actions/action-1/approve", json={"note": "x"}
        )

    assert response.status_code == 403
    assert service.approve_calls == 0
