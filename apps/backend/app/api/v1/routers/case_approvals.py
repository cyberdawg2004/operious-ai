"""SME-reviewed approval case endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.case_approvals import (
    CaseApprovalApproveRequest,
    CaseApprovalEscalateRequest,
    CaseApprovalGuideRequest,
    CaseApprovalListResponse,
    CaseApprovalRejectRequest,
    CaseApprovalResponse,
)
from app.approvals.enums import CaseApprovalEntryCategory, CaseApprovalStatus
from app.approvals.persistence import CaseApprovalQuery
from app.dependencies.authority import (
    require_authority,
    require_tenant_actions_approve,
    require_tenant_approvals_read,
    require_tenant_resolution_guide,
    require_tenant_scope,
)
from app.dependencies.services import get_case_approval_service
from app.identity import AuthorityContext
from app.services.case_approval_service import CaseApprovalService
from app.approvals.exceptions import (
    CaseApprovalGuidanceRejectedError,
    CaseApprovalLifecycleError,
    CaseApprovalNotFoundError,
    CaseApprovalRuntimeError,
)

router = APIRouter(tags=["case-approvals"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


@router.get(
    "",
    response_model=CaseApprovalListResponse,
    dependencies=[Depends(require_tenant_approvals_read)],
)
async def list_case_approvals(
    status_filter: CaseApprovalStatus | None = Query(None, alias="status"),
    entry_category: CaseApprovalEntryCategory | None = Query(None),
    session_id: str | None = Query(None),
    execution_id: str | None = Query(None),
    dispatch_id: str | None = Query(None),
    resolution_proposal_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalListResponse:
    records = await service.list_cases(
        tenant_id=expected_tenant_id,
        query=CaseApprovalQuery(
            session_id=session_id,
            execution_id=execution_id,
            dispatch_id=dispatch_id,
            resolution_proposal_id=resolution_proposal_id,
            status=status_filter.value if status_filter is not None else None,
            entry_category=(
                entry_category.value if entry_category is not None else None
            ),
            limit=limit,
            offset=offset,
        ),
    )
    return CaseApprovalListResponse(
        items=[CaseApprovalResponse.from_record(record) for record in records]
    )


@router.get(
    "/{approval_case_id}",
    response_model=CaseApprovalResponse,
    dependencies=[Depends(require_tenant_approvals_read)],
)
async def get_case_approval(
    approval_case_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalResponse:
    record = await service.get_case(
        approval_case_id=approval_case_id,
        tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "case_approval_not_found"},
        )
    return CaseApprovalResponse.from_record(record)


@router.post(
    "/{approval_case_id}/approve",
    response_model=CaseApprovalResponse,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def approve_case_approval(
    approval_case_id: str,
    request: CaseApprovalApproveRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalResponse:
    try:
        record = await service.approve_case(
            approval_case_id=approval_case_id,
            tenant_id=expected_tenant_id,
            approved_by=_principal_or_400(authority),
            note=request.note,
        )
    except CaseApprovalNotFoundError as exc:
        raise _not_found(exc)
    except CaseApprovalLifecycleError as exc:
        raise _conflict("case_approval_lifecycle_conflict", exc)
    except CaseApprovalRuntimeError as exc:
        raise _bad_request("case_approval_approve_failed", exc)
    return CaseApprovalResponse.from_record(record)


@router.post(
    "/{approval_case_id}/guide",
    response_model=CaseApprovalResponse,
    dependencies=[Depends(require_tenant_resolution_guide)],
)
async def guide_case_approval(
    approval_case_id: str,
    request: CaseApprovalGuideRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalResponse:
    try:
        record = await service.guide_case(
            approval_case_id=approval_case_id,
            tenant_id=expected_tenant_id,
            guided_by=_principal_or_400(authority),
            guidance=request.guidance,
        )
    except CaseApprovalNotFoundError as exc:
        raise _not_found(exc)
    except CaseApprovalGuidanceRejectedError as exc:
        raise _bad_request("case_approval_guidance_rejected", exc)
    except CaseApprovalLifecycleError as exc:
        raise _conflict("case_approval_guidance_conflict", exc)
    return CaseApprovalResponse.from_record(record)


@router.post(
    "/{approval_case_id}/reject",
    response_model=CaseApprovalResponse,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def reject_case_approval(
    approval_case_id: str,
    request: CaseApprovalRejectRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalResponse:
    try:
        record = await service.reject_case(
            approval_case_id=approval_case_id,
            tenant_id=expected_tenant_id,
            rejected_by=_principal_or_400(authority),
            reason=request.reason,
        )
    except CaseApprovalNotFoundError as exc:
        raise _not_found(exc)
    except CaseApprovalLifecycleError as exc:
        raise _conflict("case_approval_lifecycle_conflict", exc)
    except CaseApprovalRuntimeError as exc:
        raise _bad_request("case_approval_reject_failed", exc)
    return CaseApprovalResponse.from_record(record)


@router.post(
    "/{approval_case_id}/escalate",
    response_model=CaseApprovalResponse,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def escalate_case_approval(
    approval_case_id: str,
    request: CaseApprovalEscalateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CaseApprovalService = Depends(get_case_approval_service),
) -> CaseApprovalResponse:
    try:
        record = await service.escalate_case(
            approval_case_id=approval_case_id,
            tenant_id=expected_tenant_id,
            escalated_by=_principal_or_400(authority),
            reason=request.reason,
        )
    except CaseApprovalNotFoundError as exc:
        raise _not_found(exc)
    except CaseApprovalLifecycleError as exc:
        raise _conflict("case_approval_escalate_conflict", exc)
    except CaseApprovalRuntimeError as exc:
        raise _bad_request("case_approval_escalate_failed", exc)
    return CaseApprovalResponse.from_record(record)


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "case_approval_not_found"},
    )


def _conflict(code: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code},
    )


def _bad_request(code: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code},
    )


__all__ = ["router"]
