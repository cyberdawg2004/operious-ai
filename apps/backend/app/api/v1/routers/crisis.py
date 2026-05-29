"""Crisis-mode governance endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from app.api.v1.schemas.crisis import (
    CrisisDeploymentListResponse,
    CrisisDeploymentResponse,
    CrisisDeployRequest,
    deployment_scope_from_request,
)
from app.dependencies.authority import (
    require_operator_authority,
    require_tenant_scope,
)
from app.dependencies.services import get_crisis_service
from app.identity import AuthorityContext
from app.services.crisis_service import CrisisService, CrisisServiceError

router = APIRouter(tags=["crisis"])


@router.post("/deploy", response_model=CrisisDeploymentResponse)
async def deploy_crisis_rule(
    request: CrisisDeployRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    operator: AuthorityContext = Depends(require_operator_authority),
    service: CrisisService = Depends(get_crisis_service),
) -> CrisisDeploymentResponse:
    try:
        record = await service.deploy(
            tenant_id=expected_tenant_id,
            template=request.template,
            scope=deployment_scope_from_request(
                request.template,
                request.scope,
            ),
            ttl_minutes=request.ttl_minutes,
            deployed_by=str(operator.principal_id or "operator"),
            expected_tenant_id=expected_tenant_id,
            dry_run=request.dry_run,
        )
    except CrisisServiceError as exc:
        raise _http_error(exc) from exc
    return CrisisDeploymentResponse.from_record(record)


@router.get("/active", response_model=CrisisDeploymentListResponse)
async def list_active_crisis_rules(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CrisisService = Depends(get_crisis_service),
) -> CrisisDeploymentListResponse:
    records = await service.list_active(
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
    )
    return CrisisDeploymentListResponse(
        items=[CrisisDeploymentResponse.from_record(record) for record in records]
    )


@router.delete("/{deployment_id}", response_model=CrisisDeploymentResponse)
async def deactivate_crisis_rule(
    deployment_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    operator: AuthorityContext = Depends(require_operator_authority),
    service: CrisisService = Depends(get_crisis_service),
) -> CrisisDeploymentResponse:
    try:
        record = await service.deactivate(
            deployment_id=deployment_id,
            deactivated_by=str(operator.principal_id or "operator"),
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
    except CrisisServiceError as exc:
        raise _http_error(exc) from exc
    return CrisisDeploymentResponse.from_record(record)


@router.get("/ticker")
async def crisis_ticker(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CrisisService = Depends(get_crisis_service),
) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in service.stream_intercepts(
            expected_tenant_id=expected_tenant_id,
        ):
            yield {
                "event": str(event.get("type") or "message"),
                "data": json.dumps(event, default=str),
            }

    return EventSourceResponse(events())


def _http_error(exc: CrisisServiceError) -> HTTPException:
    message = str(exc)
    status_code = status.HTTP_400_BAD_REQUEST
    code = "crisis_request_failed"
    if "not found" in message:
        status_code = status.HTTP_404_NOT_FOUND
        code = "crisis_deployment_not_found"
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


__all__ = ["router"]
