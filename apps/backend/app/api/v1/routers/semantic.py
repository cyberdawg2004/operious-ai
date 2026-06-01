"""Semantic operator review endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.semantic import (
    SemanticCircuitEventResponse,
    SemanticCircuitEventResponseList,
    SemanticCircuitStateResponse,
    SemanticCircuitStateResponseList,
    SemanticQuarantineReleaseRequest,
    SemanticQuarantineResponse,
    SemanticQuarantineResponseList,
    SemanticQuarantineStatus,
)
from app.dependencies.authority import (
    require_authority,
    require_tenant_knowledge_write,
    require_tenant_observability_read,
    require_tenant_scope,
)
from app.dependencies.services import (
    get_quarantine_service,
    get_semantic_circuit_service,
)
from app.identity import AuthorityContext
from app.services.semantic_circuit_service import SemanticCircuitService
from app.services.quarantine_service import (
    QuarantineService,
    SemanticQuarantineAlreadyReviewedError,
    SemanticQuarantineNotFoundError,
)

router = APIRouter(tags=["semantic"])


@router.get(
    "/circuit-states",
    response_model=SemanticCircuitStateResponseList,
    dependencies=[Depends(require_tenant_observability_read)],
)
async def list_semantic_circuit_states(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: SemanticCircuitService = Depends(get_semantic_circuit_service),
) -> list[SemanticCircuitStateResponse]:
    records = await service.list_states(
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
    )
    return [SemanticCircuitStateResponse.from_record(record) for record in records]


@router.get(
    "/circuit-events",
    response_model=SemanticCircuitEventResponseList,
    dependencies=[Depends(require_tenant_observability_read)],
)
async def list_semantic_circuit_events(
    channel: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=500),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: SemanticCircuitService = Depends(get_semantic_circuit_service),
) -> list[SemanticCircuitEventResponse]:
    records = await service.list_events(
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
        channel=channel,
        limit=limit,
    )
    return [SemanticCircuitEventResponse.from_record(record) for record in records]


@router.get(
    "/quarantine",
    response_model=SemanticQuarantineResponseList,
    dependencies=[Depends(require_tenant_observability_read)],
)
async def list_semantic_quarantine(
    status_filter: SemanticQuarantineStatus = Query(
        "pending",
        alias="status",
    ),
    limit: int = Query(50, ge=1, le=500),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: QuarantineService = Depends(get_quarantine_service),
) -> list[SemanticQuarantineResponse]:
    records = await service.list_records(
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
        status=status_filter,
        limit=limit,
    )
    return [SemanticQuarantineResponse.from_record(record) for record in records]


@router.post(
    "/quarantine/{quarantine_id}/release",
    response_model=SemanticQuarantineResponse,
    dependencies=[Depends(require_tenant_knowledge_write)],
)
async def release_semantic_quarantine(
    quarantine_id: str,
    request: SemanticQuarantineReleaseRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: QuarantineService = Depends(get_quarantine_service),
) -> SemanticQuarantineResponse:
    try:
        record = await service.release(
            quarantine_id=quarantine_id,
            verdict=request.verdict,
            reviewed_by=_principal_or_400(authority),
            note=request.note,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
    except SemanticQuarantineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "semantic_quarantine_not_found"},
        ) from exc
    except SemanticQuarantineAlreadyReviewedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "semantic_quarantine_already_reviewed"},
        ) from exc
    return SemanticQuarantineResponse.from_record(record)


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
