"""Cognition Hub endpoints for reviewed knowledge evolution."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.cognition import (
    ApprovalApplicationResponse,
    ApprovalLifecycleResponse,
    CognitionAuditRecordResponse,
    KnowledgeDocumentVersionPageResponse,
    KnowledgeRollbackRequest,
    KnowledgeRollbackResponse,
)
from app.cognition.exceptions import (
    CognitionError,
    CognitionLifecycleError,
    CognitionNotFoundError,
    CognitionSeparationError,
)
from app.dependencies.authority import (
    require_authority,
    require_tenant_cognition_read,
    require_tenant_knowledge_approve,
    require_tenant_knowledge_write,
    require_tenant_scope,
)
from app.identity import AuthorityContext
from app.dependencies.services import get_cognition_service
from app.services.cognition_service import CognitionService

router = APIRouter(tags=["cognition"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.post(
    "/approvals/{approval_id}/approve",
    response_model=ApprovalLifecycleResponse,
    # F7: approve requires tenant.knowledge.approve, NOT tenant.knowledge.write.
    # This enforces dual-control: the proposer (who has .write) cannot also approve.
    dependencies=[Depends(require_tenant_knowledge_approve)],
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
    except CognitionSeparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "approval_separation_required"},
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
    # F7: apply also requires tenant.knowledge.approve — not knowledge.write.
    dependencies=[Depends(require_tenant_knowledge_approve)],
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
    except CognitionSeparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "approval_separation_required"},
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
    dependencies=[Depends(require_tenant_cognition_read)],
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


@router.get(
    "/audits/{audit_id}",
    response_model=CognitionAuditRecordResponse,
    dependencies=[Depends(require_tenant_cognition_read)],
)
async def get_cognition_audit_record(
    audit_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: CognitionService = Depends(get_cognition_service),
) -> CognitionAuditRecordResponse:
    try:
        record = await service.get_cognition_audit_record(
            tenant_id=expected_tenant_id,
            audit_id=audit_id,
        )
    except CognitionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "cognition_audit_record_not_found"},
        ) from exc
    except CognitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "cognition_audit_read_failed"},
        ) from exc
    return CognitionAuditRecordResponse.from_record(record)


@router.post(
    "/knowledge/{document_id}/rollback",
    response_model=KnowledgeRollbackResponse,
    dependencies=[Depends(require_tenant_knowledge_write)],
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
            approval_id=request.approval_id,
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
