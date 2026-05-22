"""Cognition Hub endpoints for reviewed knowledge evolution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.cognition import (
    ApprovalApplicationResponse,
    ApprovalLifecycleResponse,
    KnowledgeDocumentVersionPageResponse,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResponse,
)
from app.cognition.exceptions import (
    CognitionError,
    CognitionLifecycleError,
    CognitionNotFoundError,
)
from app.dependencies.authority import require_authority, require_tenant_scope
from app.identity import AuthorityContext
from app.dependencies.services import get_cognition_service
from app.services.cognition_service import CognitionService

router = APIRouter(tags=["cognition"])

_MIN_LIMIT = 1
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalLifecycleResponse,
)
async def approve_approval(
    approval_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CognitionService = Depends(get_cognition_service),
) -> ApprovalLifecycleResponse:
    try:
        result = await service.approve_approval(
            tenant_id=expected_tenant_id,
            approval_id=approval_id,
            reviewed_by=_principal_or_400(authority),
        )
    except CognitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "approval_record_not_found"},
        ) from exc
    except CognitionLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "approval_lifecycle_conflict"},
        ) from exc
    return ApprovalLifecycleResponse.from_result(result)


@router.post(
    "/approvals/{approval_id}/apply",
    response_model=ApprovalApplicationResponse,
)
async def apply_approval(
    approval_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CognitionService = Depends(get_cognition_service),
) -> ApprovalApplicationResponse:
    try:
        result = await service.apply_approval(
            tenant_id=expected_tenant_id,
            approval_id=approval_id,
            applied_by=_principal_or_400(authority),
        )
    except CognitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "approval_record_not_found"},
        ) from exc
    except CognitionLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "approval_lifecycle_conflict"},
        ) from exc
    except CognitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "approval_apply_failed"},
        ) from exc
    return ApprovalApplicationResponse.from_result(result)


@router.get(
    "/knowledge/versions",
    response_model=KnowledgeDocumentVersionPageResponse,
)
async def list_knowledge_document_versions(
    document_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    source_approval_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CognitionService = Depends(get_cognition_service),
) -> KnowledgeDocumentVersionPageResponse:
    page = await service.list_document_versions(
        tenant_id=expected_tenant_id,
        document_id=document_id,
        status=status_filter,
        source_approval_id=source_approval_id,
        limit=limit,
        offset=offset,
    )
    return KnowledgeDocumentVersionPageResponse.from_page(page)


@router.post(
    "/knowledge/{document_id}/rollback",
    response_model=KnowledgeRollbackResponse,
)
async def rollback_knowledge_document(
    document_id: str,
    request: KnowledgeRollbackRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: CognitionService = Depends(get_cognition_service),
) -> KnowledgeRollbackResponse:
    try:
        result = await service.rollback_document(
            tenant_id=expected_tenant_id,
            document_id=document_id,
            target_version=request.target_version,
            rolled_back_by=_principal_or_400(authority),
        )
    except (ValueError, CognitionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "knowledge_document_version_not_found"},
        ) from exc
    return KnowledgeRollbackResponse.from_result(result)


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
