"""Signed tenant audit export endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas.audit_export import (
    AuditExportResponse,
    AuditExportVerifyRequest,
    AuditExportVerifyResponse,
)
from app.dependencies.authority import (
    request_tenant_scope_opt,
    require_tenant_audit_export,
    require_tenant_scope,
)
from app.dependencies.services import get_audit_export_service
from app.identity import AuthorityContext
from app.services.audit_export_service import (
    AuditExportNotConfiguredError,
    AuditExportService,
)

router = APIRouter(tags=["audit"])

# Tighter per-endpoint cap to bound HMAC CPU cost on the public verify path
# (#81). The global RequestBodyLimitMiddleware ceiling (1 MiB) still applies
# as the outer guard.
_VERIFY_MAX_BODY_BYTES = 256 * 1024  # 256 KiB


@router.get("/export", response_model=AuditExportResponse)
async def create_audit_export(
    from_timestamp: datetime | None = Query(default=None),
    to_timestamp: datetime | None = Query(default=None),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _auth: AuthorityContext = Depends(require_tenant_audit_export),
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
    raw_request: Request,
    body: AuditExportVerifyRequest,
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: AuditExportService = Depends(get_audit_export_service),
) -> AuditExportVerifyResponse:
    # POST /api/v1/audit/verify is intentionally unauthenticated. Anyone who
    # holds a signed audit export should be able to verify its authenticity
    # without requiring a session. The endpoint recomputes the HMAC and compares
    # signatures; it does not return tenant data beyond what is already present
    # in the provided export.
    #
    # Body size is capped tightly here (256 KiB) to bound the HMAC CPU cost
    # without relying solely on the global 1 MiB RequestBodyLimitMiddleware (#81).
    # Starlette caches the body on first read, so `body` above still works.
    raw = await raw_request.body()
    if len(raw) > _VERIFY_MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "code": "audit_export_too_large",
                "max_bytes": _VERIFY_MAX_BODY_BYTES,
            },
        )
    try:
        result = service.verify_export(export=body.export)
    except AuditExportNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit_export_not_configured",
        ) from exc
    return AuditExportVerifyResponse.from_verification(result)


__all__ = ["router"]
