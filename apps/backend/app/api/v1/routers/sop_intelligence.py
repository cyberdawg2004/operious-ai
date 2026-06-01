"""SOP intelligence proposal read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.sop_intelligence import (
    ApprovalRecordPage,
    ApprovalRecordResponse,
)
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_sop_intelligence_service
from app.services.sop_intelligence_service import SOPIntelligenceService
from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.persistence import ApprovalQuery

router = APIRouter(tags=["sop-intelligence"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.get(
    "/{approval_id}",
    response_model=ApprovalRecordResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def get_approval_record(
    approval_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: SOPIntelligenceService = Depends(get_sop_intelligence_service),
) -> ApprovalRecordResponse:
    record = await service.get_approval_record(
        approval_id=approval_id,
        tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "approval_record_not_found"},
        )
    return ApprovalRecordResponse.from_record(record)


@router.get(
    "",
    response_model=ApprovalRecordPage,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def list_approval_records(
    status_filter: ApprovalStatus | None = Query(None, alias="status"),
    document_id: str | None = Query(None),
    min_confidence: float | None = Query(None, ge=0, le=1),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: SOPIntelligenceService = Depends(get_sop_intelligence_service),
) -> ApprovalRecordPage:
    page = await service.list_approval_records(
        tenant_id=expected_tenant_id,
        query=ApprovalQuery(
            document_id=document_id,
            status=status_filter.value if status_filter is not None else None,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        ),
    )
    return ApprovalRecordPage(
        items=[
            ApprovalRecordResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


__all__ = ["router"]
