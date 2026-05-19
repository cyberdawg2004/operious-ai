"""Supervisor read endpoints — v1 transport layer (PR-D7).

Five read endpoints over the four supervisor record types:

* GET /inspections/{inspection_id}                      → apex
* GET /inspections                                       → page
* GET /inspections/{inspection_id}/findings             → sub-record
* GET /inspections/{inspection_id}/evaluations          → sub-record
* GET /inspections/{inspection_id}/escalations          → sub-record

Sub-records inherit tenant scope from their owning inspection
(per PR-B6 contract) — the substrate's parent lookup handles
this transparently; the router just forwards expected_tenant_id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.supervisor import (
    EscalationDecisionSchema,
    InspectionEscalationsResponse,
    InspectionEvaluationsResponse,
    InspectionFindingsResponse,
    InspectionResponse,
    InspectionsPage,
    QAEvaluationSchema,
    RuntimeFindingSchema,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_supervisor_repository
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    InspectionQuery,
)

router = APIRouter(tags=["supervisor"])

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


@router.get(
    "/inspections/{inspection_id}",
    response_model=InspectionResponse,
)
async def get_inspection(
    inspection_id: str,
    repo: BaseSupervisorRepository = Depends(get_supervisor_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InspectionResponse:
    record = await repo.get_inspection(
        inspection_id, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "inspection_not_found"}
        )
    return InspectionResponse.from_record(record)


@router.get(
    "/inspections",
    response_model=InspectionsPage,
)
async def list_inspections(
    execution_id: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    runtime_instance_id: str | None = Query(None),
    decision_kind: str | None = Query(None),
    inspection_mode: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: BaseSupervisorRepository = Depends(get_supervisor_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InspectionsPage:
    query = InspectionQuery(
        execution_id=execution_id,
        correlation_id=correlation_id,
        request_id=request_id,
        runtime_instance_id=runtime_instance_id,
        decision_kind=decision_kind,
        inspection_mode=inspection_mode,
        limit=limit,
        offset=offset,
    )
    page = await repo.query_inspections(
        query, expected_tenant_id=expected_tenant_id
    )
    return InspectionsPage(
        items=[InspectionResponse.from_record(r) for r in page.items],
        total=page.total,
        offset=page.offset,
    )


@router.get(
    "/inspections/{inspection_id}/findings",
    response_model=InspectionFindingsResponse,
)
async def list_findings(
    inspection_id: str,
    repo: BaseSupervisorRepository = Depends(get_supervisor_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InspectionFindingsResponse:
    findings = await repo.get_findings_for_inspection(
        inspection_id, expected_tenant_id=expected_tenant_id
    )
    return InspectionFindingsResponse(
        inspection_id=inspection_id,
        items=[RuntimeFindingSchema.from_record(f) for f in findings],
    )


@router.get(
    "/inspections/{inspection_id}/evaluations",
    response_model=InspectionEvaluationsResponse,
)
async def list_evaluations(
    inspection_id: str,
    repo: BaseSupervisorRepository = Depends(get_supervisor_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InspectionEvaluationsResponse:
    evaluations = await repo.get_evaluations_for_inspection(
        inspection_id, expected_tenant_id=expected_tenant_id
    )
    return InspectionEvaluationsResponse(
        inspection_id=inspection_id,
        items=[
            QAEvaluationSchema.from_record(e) for e in evaluations
        ],
    )


@router.get(
    "/inspections/{inspection_id}/escalations",
    response_model=InspectionEscalationsResponse,
)
async def list_escalations(
    inspection_id: str,
    repo: BaseSupervisorRepository = Depends(get_supervisor_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> InspectionEscalationsResponse:
    escalations = await repo.get_escalations_for_inspection(
        inspection_id, expected_tenant_id=expected_tenant_id
    )
    return InspectionEscalationsResponse(
        inspection_id=inspection_id,
        items=[
            EscalationDecisionSchema.from_record(e) for e in escalations
        ],
    )


__all__ = ["router"]
