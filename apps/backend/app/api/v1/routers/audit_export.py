"""Signed tenant audit export endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.audit_export import (
    AuditExportResponse,
    AuditExportVerifyRequest,
    AuditExportVerifyResponse,
)
from app.dependencies.authority import (
    request_tenant_scope_opt,
    require_tenant_scope,
)
from app.dependencies.services import get_audit_export_service
from app.services.audit_export_service import (
    AuditExportNotConfiguredError,
    AuditExportService,
)

router = APIRouter(tags=["audit"])


@router.get("/export", response_model=AuditExportResponse)
async def create_audit_export(
    from_timestamp: datetime | None = Query(default=None),
    to_timestamp: datetime | None = Query(default=None),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: AuditExportService = Depends(get_audit_export_service),
) -> AuditExportResponse:
    try:
        export = await service.create_export(
            tenant_id=expected_tenant_id,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
    except AuditExportNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit_export_not_configured",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_audit_export_window"},
        ) from exc
    return AuditExportResponse.from_export(export)


@router.post("/verify", response_model=AuditExportVerifyResponse)
async def verify_audit_export(
    request: AuditExportVerifyRequest,
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: AuditExportService = Depends(get_audit_export_service),
) -> AuditExportVerifyResponse:
    try:
        result = service.verify_export(export=request.export)
    except AuditExportNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit_export_not_configured",
        ) from exc
    return AuditExportVerifyResponse.from_verification(result)


__all__ = ["router"]
