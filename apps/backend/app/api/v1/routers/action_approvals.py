"""Manager action approval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.action_approvals import (
    ActionApprovalDetailResponse,
    ActionApprovalListResponse,
    ActionApprovalSummaryResponse,
    ApproveActionApprovalRequest,
    DenyActionApprovalRequest,
)
from app.dependencies.authority import (
    require_authority,
    require_tenant_actions_approve,
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_action_approval_service
from app.identity import AuthorityContext
from app.services.action_approval_service import (
    ActionApprovalLifecycleError,
    ActionApprovalNotFoundError,
    ActionApprovalRuntimeError,
    ActionApprovalService,
)
from app.services.case_approval_service import CaseApprovalRuntimeError

router = APIRouter(tags=["action-approvals"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


@router.get(
    "",
    response_model=ActionApprovalListResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def list_action_approvals(
    status_filter: str = Query("pending", alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: ActionApprovalService = Depends(get_action_approval_service),
) -> ActionApprovalListResponse:
    records = await service.list_by_status(
        status=status_filter,
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
        limit=limit,
        offset=offset,
    )
    return ActionApprovalListResponse(
        items=[
            ActionApprovalSummaryResponse.from_record(record)
            for record in records
        ]
    )


@router.get(
    "/{approval_id}",
    response_model=ActionApprovalDetailResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def get_action_approval(
    approval_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: ActionApprovalService = Depends(get_action_approval_service),
) -> ActionApprovalDetailResponse:
    try:
        context = await service.get_with_context(
            approval_id=approval_id,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
    except ActionApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "action_approval_not_found"},
        ) from exc
    return ActionApprovalDetailResponse.from_context(context)


@router.post(
    "/{approval_id}/approve",
    response_model=ActionApprovalSummaryResponse,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def approve_action_approval(
    approval_id: str,
    request: ApproveActionApprovalRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: ActionApprovalService = Depends(get_action_approval_service),
) -> ActionApprovalSummaryResponse:
    try:
        record = await service.approve(
            approval_id=approval_id,
            approved_by=_principal_or_400(authority),
            note=request.note,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
    except ActionApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "action_approval_not_found"},
        ) from exc
    except ActionApprovalLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "action_approval_lifecycle_conflict"},
        ) from exc
    except ActionApprovalRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "action_approval_failed"},
        ) from exc
    except CaseApprovalRuntimeError as exc:
        # The action itself resolved fine, but it's bound to a case whose
        # reply couldn't be completed (e.g. a clean governance denial) --
        # claim_and_complete_case_for_action rolled the whole transaction
        # back, so neither half landed. Distinct from action_approval_
        # failed: the action approval surface is fine, the linked case's
        # content is the actual blocker.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "case_completion_failed"},
        ) from exc
    return ActionApprovalSummaryResponse.from_record(record)


@router.post(
    "/{approval_id}/deny",
    response_model=ActionApprovalSummaryResponse,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def deny_action_approval(
    approval_id: str,
    request: DenyActionApprovalRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: ActionApprovalService = Depends(get_action_approval_service),
) -> ActionApprovalSummaryResponse:
    try:
        record = await service.deny(
            approval_id=approval_id,
            denied_by=_principal_or_400(authority),
            reason=request.reason,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
    except ActionApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "action_approval_not_found"},
        ) from exc
    except ActionApprovalLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "action_approval_lifecycle_conflict"},
        ) from exc
    except ActionApprovalRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "action_approval_denial_failed"},
        ) from exc
    except CaseApprovalRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "case_completion_failed"},
        ) from exc
    return ActionApprovalSummaryResponse.from_record(record)


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
