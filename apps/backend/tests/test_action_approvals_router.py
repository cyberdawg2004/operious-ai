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
from app.dependencies.authority import TENANT_ACTIONS_APPROVE_CAPABILITY
from app.dependencies.services import get_action_approval_service
from app.identity import AuthorityContext

_TENANT = "tenant-action-approvals-router"


class _CaseCompletionFailsService:
    async def approve(self, **kwargs: object) -> object:
        raise CaseApprovalRuntimeError(
            "revised SME reply failed resolution governance (deny); "
            "escalate the case"
        )

    async def deny(self, **kwargs: object) -> object:
        raise CaseApprovalRuntimeError(
            "revised SME reply failed resolution governance (deny); "
            "escalate the case"
        )


def _test_app(service: object) -> FastAPI:
    app = FastAPI()
    authority = AuthorityContext.from_raw(
        tenant_id=_TENANT,
        principal_id="operator-approve",
        capabilities=frozenset({TENANT_ACTIONS_APPROVE_CAPABILITY}),
    )

    @app.middleware("http")
    async def _bind_authority(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.authority = authority
        return await call_next(request)

    app.dependency_overrides[get_action_approval_service] = lambda: service
    app.include_router(action_approvals_router, prefix="/approvals/actions")
    return app


@pytest.mark.asyncio
async def test_approve_surfaces_case_completion_failure_as_clean_400() -> None:
    transport = httpx.ASGITransport(app=_test_app(_CaseCompletionFailsService()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/actions/action-1/approve", json={"note": "looks good"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "case_completion_failed"}


@pytest.mark.asyncio
async def test_deny_surfaces_case_completion_failure_as_clean_400() -> None:
    transport = httpx.ASGITransport(app=_test_app(_CaseCompletionFailsService()))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/approvals/actions/action-1/deny", json={"reason": "no longer needed"}
        )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "case_completion_failed"}
