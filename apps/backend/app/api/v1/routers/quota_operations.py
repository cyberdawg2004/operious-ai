"""Operator quota and provider circuit operations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.quota_operations import (
    ProviderQuotaRecordPageResponse,
    ProviderQuotaRecordResponse,
    QuotaCircuitOverrideRequest,
    QuotaStatusResponse,
)
from app.dependencies.authority import (
    require_operator_authority,
    require_tenant_scope,
)
from app.dependencies.services import get_quota_operations_service
from app.identity import AuthorityContext
from app.services.quota_operations_service import (
    QuotaOperationsService,
    QuotaRecordNotFoundError,
    QuotaTenantScopeError,
)

router = APIRouter(tags=["quota"])

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100


@router.get(
    "/status/{tenant_id}/{provider}/{model}",
    response_model=QuotaStatusResponse,
)
async def get_quota_status(
    tenant_id: str,
    provider: str,
    model: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_operator_authority),
    service: QuotaOperationsService = Depends(get_quota_operations_service),
) -> QuotaStatusResponse:
    _ = authority
    try:
        quota_status = await service.get_quota_status(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            provider=provider,
            model=model,
        )
    except QuotaTenantScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "quota_tenant_scope_forbidden"},
        ) from exc
    return QuotaStatusResponse.from_status(quota_status)


@router.post(
    "/circuit/{tenant_id}/{provider}",
    response_model=ProviderQuotaRecordResponse,
)
async def set_provider_circuit_override(
    tenant_id: str,
    provider: str,
    request: QuotaCircuitOverrideRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_operator_authority),
    service: QuotaOperationsService = Depends(get_quota_operations_service),
) -> ProviderQuotaRecordResponse:
    try:
        record = await service.set_operator_override(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            provider=provider,
            circuit_state=request.circuit_state,
            set_by=_operator_principal(authority),
            reason=request.reason,
        )
    except QuotaTenantScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "quota_tenant_scope_forbidden"},
        ) from exc
    except QuotaRecordNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "quota_record_not_found"},
        ) from exc
    return ProviderQuotaRecordResponse.from_record(record)


@router.get(
    "/records/{tenant_id}",
    response_model=ProviderQuotaRecordPageResponse,
)
async def list_provider_quota_records(
    tenant_id: str,
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_operator_authority),
    service: QuotaOperationsService = Depends(get_quota_operations_service),
) -> ProviderQuotaRecordPageResponse:
    _ = authority
    try:
        page = await service.list_quota_records(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
            limit=limit,
            offset=offset,
        )
    except QuotaTenantScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "quota_tenant_scope_forbidden"},
        ) from exc
    return ProviderQuotaRecordPageResponse.from_page(page)


def _operator_principal(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "operator_principal_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
