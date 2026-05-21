"""Dispatch write endpoint (PR-W3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.v1.schemas.dispatch import (
    DispatchRequest,
    DispatchResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_dispatch_service
from app.services.dispatch_service import (
    DispatchIngressNotFoundError,
    DispatchService,
    DispatchServiceError,
)

router = APIRouter(tags=["dispatch"])


@router.post("/dispatch", response_model=DispatchResponse)
async def dispatch_ingress(
    request: DispatchRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: DispatchService = Depends(get_dispatch_service),
) -> DispatchResponse:
    try:
        result = await service.dispatch(
            ingress_id=request.ingress_id,
            tenant_id=expected_tenant_id,
        )
    except DispatchIngressNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "ingress_not_found"}
        ) from exc
    except DispatchServiceError as exc:
        raise HTTPException(
            status_code=500, detail={"code": "dispatch_failed"}
        ) from exc
    return DispatchResponse(
        dispatch_id=result.dispatch_id,
        session_id=result.session_id,
        governance_decision_id=result.governance_decision_id,
        verdict=result.verdict,
    )


__all__ = ["router"]
