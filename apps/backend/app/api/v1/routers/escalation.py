"""Escalation queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.escalation import (
    EscalationPage,
    EscalationResolutionRequest,
    EscalationResponse,
)
from app.dependencies.authority import require_authority, require_tenant_scope
from app.dependencies.services import get_escalation_service
from app.escalation.enums import EscalationStatus
from app.escalation.exceptions import (
    EscalationError,
    EscalationNotFoundError,
    EscalationResolutionError,
    EscalationRuntimeError,
)
from app.escalation.persistence import EscalationQuery
from app.identity import AuthorityContext
from app.services.escalation_service import EscalationService

router = APIRouter(tags=["escalation"])

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


@router.get(
    "/{escalation_id}",
    response_model=EscalationResponse,
)
async def get_escalation(
    escalation_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: EscalationService = Depends(get_escalation_service),
) -> EscalationResponse:
    record = await service.get_escalation(
        escalation_id=escalation_id,
        tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "escalation_not_found"},
        )
    return EscalationResponse.from_record(record)


@router.get(
    "",
    response_model=EscalationPage,
)
async def list_escalations(
    status_filter: EscalationStatus | None = Query(None, alias="status"),
    session_id: str | None = Query(None),
    governance_decision_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: EscalationService = Depends(get_escalation_service),
) -> EscalationPage:
    page = await service.list_escalations(
        tenant_id=expected_tenant_id,
        query=EscalationQuery(
            session_id=session_id,
            governance_decision_id=governance_decision_id,
            status=status_filter.value if status_filter is not None else None,
            limit=limit,
            offset=offset,
        ),
    )
    return EscalationPage(
        items=[EscalationResponse.from_record(record) for record in page.items],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/{escalation_id}/approve",
    response_model=EscalationResponse,
)
async def approve_escalation(
    escalation_id: str,
    request: EscalationResolutionRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: EscalationService = Depends(get_escalation_service),
) -> EscalationResponse:
    try:
        record = await service.approve_escalation(
            escalation_id=escalation_id,
            tenant_id=expected_tenant_id,
            resolution=request.resolution,
            resolved_by=_principal_or_400(authority),
        )
    except EscalationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "escalation_not_found"},
        ) from exc
    except EscalationResolutionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "escalation_not_resolvable"},
        ) from exc
    except (EscalationRuntimeError, EscalationError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "escalation_approval_failed"},
        ) from exc
    return EscalationResponse.from_record(record)


@router.post(
    "/{escalation_id}/reject",
    response_model=EscalationResponse,
)
async def reject_escalation(
    escalation_id: str,
    request: EscalationResolutionRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: EscalationService = Depends(get_escalation_service),
) -> EscalationResponse:
    try:
        record = await service.reject_escalation(
            escalation_id=escalation_id,
            tenant_id=expected_tenant_id,
            resolution=request.resolution,
            resolved_by=_principal_or_400(authority),
        )
    except EscalationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "escalation_not_found"},
        ) from exc
    except EscalationResolutionError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "escalation_not_resolvable"},
        ) from exc
    except (EscalationRuntimeError, EscalationError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "escalation_rejection_failed"},
        ) from exc
    return EscalationResponse.from_record(record)


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
