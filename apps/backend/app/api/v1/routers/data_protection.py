"""Data-protection operational admin endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.data_protection import (
    ErasureRequestCreateRequest,
    ErasureRequestResponse,
    LegalHoldCreateRequest,
    LegalHoldListResponse,
    LegalHoldResponse,
    RetentionPolicyRequest,
    RetentionPolicyResponse,
)
from app.data_protection.crypto import (
    DataProtectionError,
    DataProtectionService,
    ErasureRequestLifecycleError,
    ErasureRequestNotFoundError,
    ErasureRequestSeparationError,
    LegalHoldBlockedError,
    LegalHoldNotFoundError,
)
from app.dependencies.authority import (
    require_authority,
    require_tenant_privacy_admin,
    require_tenant_privacy_approve,
    require_tenant_scope,
)
from app.dependencies.database import get_db_session
from app.dependencies.services import get_data_protection_service
from app.identity import AuthorityContext

router = APIRouter(tags=["data-protection"])


@router.post(
    "/erasure-requests",
    response_model=ErasureRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def propose_erasure_request(
    request: ErasureRequestCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: DataProtectionService = Depends(get_data_protection_service),
    session: AsyncSession = Depends(get_db_session),
) -> ErasureRequestResponse:
    try:
        record = await service.propose_erasure(
            tenant_id=expected_tenant_id,
            subject_id=request.subject_id,
            reason=request.reason,
            proposed_by=_principal_or_400(authority),
        )
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "erasure_request_invalid"},
        ) from exc
    await session.commit()
    return ErasureRequestResponse.from_record(record)


@router.post(
    "/erasure-requests/{request_id}/approve",
    response_model=ErasureRequestResponse,
    dependencies=[Depends(require_tenant_privacy_approve)],
)
async def approve_erasure_request(
    request_id: uuid.UUID,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: DataProtectionService = Depends(get_data_protection_service),
    session: AsyncSession = Depends(get_db_session),
) -> ErasureRequestResponse:
    try:
        record = await service.approve_erasure(
            tenant_id=expected_tenant_id,
            request_id=request_id,
            approved_by=_principal_or_400(authority),
        )
    except LegalHoldBlockedError as exc:
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "legal_hold_blocks_erasure"},
        ) from exc
    except ErasureRequestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "erasure_request_not_found"},
        ) from exc
    except ErasureRequestSeparationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "erasure_approver_must_differ"},
        ) from exc
    except ErasureRequestLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "erasure_request_lifecycle_error"},
        ) from exc
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "erasure_request_invalid"},
        ) from exc
    await session.commit()
    return ErasureRequestResponse.from_record(record)


@router.post(
    "/legal-holds",
    response_model=LegalHoldResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def create_legal_hold(
    request: LegalHoldCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: DataProtectionService = Depends(get_data_protection_service),
    session: AsyncSession = Depends(get_db_session),
) -> LegalHoldResponse:
    try:
        hold_id = await service.create_legal_hold(
            tenant_id=expected_tenant_id,
            scope=request.scope,
            scope_id=request.scope_id,
            reason=request.reason,
            created_by=_principal_or_400(authority),
        )
        record = await service.get_legal_hold(
            tenant_id=expected_tenant_id,
            hold_id=hold_id,
        )
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "legal_hold_invalid"},
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "legal_hold_create_failed"},
        )
    await session.commit()
    return LegalHoldResponse.from_record(record)


@router.get(
    "/legal-holds",
    response_model=LegalHoldListResponse,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def list_legal_holds(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: DataProtectionService = Depends(get_data_protection_service),
) -> LegalHoldListResponse:
    records = await service.list_legal_holds(tenant_id=expected_tenant_id)
    return LegalHoldListResponse(
        items=[LegalHoldResponse.from_record(record) for record in records]
    )


@router.delete(
    "/legal-holds/{hold_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def release_legal_hold(
    hold_id: uuid.UUID,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: DataProtectionService = Depends(get_data_protection_service),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        await service.release_legal_hold(
            tenant_id=expected_tenant_id,
            hold_id=hold_id,
            lifted_by=_principal_or_400(authority),
        )
    except LegalHoldNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "legal_hold_not_found"},
        ) from exc
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "legal_hold_invalid"},
        ) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/retention-policy",
    response_model=RetentionPolicyResponse,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def set_retention_policy(
    request: RetentionPolicyRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: DataProtectionService = Depends(get_data_protection_service),
    session: AsyncSession = Depends(get_db_session),
) -> RetentionPolicyResponse:
    try:
        await service.set_retention_policy(
            tenant_id=expected_tenant_id,
            retention_days=request.retention_days,
            updated_by=_principal_or_400(authority),
        )
    except DataProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "retention_policy_invalid"},
        ) from exc
    await session.commit()
    return RetentionPolicyResponse(
        tenant_id=expected_tenant_id,
        retention_days=request.retention_days,
    )


@router.get(
    "/retention-policy",
    response_model=RetentionPolicyResponse,
    dependencies=[Depends(require_tenant_privacy_admin)],
)
async def get_retention_policy(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: DataProtectionService = Depends(get_data_protection_service),
) -> RetentionPolicyResponse:
    retention_days = await service.retention_days_for_tenant(expected_tenant_id)
    return RetentionPolicyResponse(
        tenant_id=expected_tenant_id,
        retention_days=retention_days,
    )


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
