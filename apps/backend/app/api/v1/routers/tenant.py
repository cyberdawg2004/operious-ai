"""Tenant-owned configuration endpoints (Phase 2.5-A)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.tenant import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationResponse,
    TenantChannelCreateRequest,
    TenantChannelUpdateRequest,
    TenantExecutionCircuitBreakerPage,
    TenantExecutionCircuitBreakerResponse,
    TenantExecutionGovernanceCreateRequest,
    TenantExecutionGovernancePage,
    TenantExecutionGovernanceResponse,
    TenantGovernancePolicyCreateRequest,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyResponse,
    TenantGovernancePolicyUpdateRequest,
    TenantKnowledgeCreateRequest,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentResponse,
    TenantKnowledgeUpdateRequest,
    TenantTopologyConfigurationCreateRequest,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationResponse,
)
from app.dependencies.authority import require_authority, require_tenant_scope
from app.dependencies.services import get_tenant_configuration_service
from app.identity import AuthorityContext
from app.services.tenant_configuration_service import (
    TenantConfigurationService,
)
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantExecutionCircuitState,
    TenantExecutionGovernanceStatus,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantTopologyStatus,
)
from app.tenant.exceptions import (
    TenantConfigurationError,
    TenantConfigurationNotFoundError,
    TenantTopologyCycleError,
)
from app.tenant.identity import (
    as_channel_configuration_id,
    as_governance_policy_id,
    as_knowledge_document_id,
)

router = APIRouter(tags=["tenant"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.post(
    "/channels",
    response_model=TenantChannelConfigurationResponse,
)
async def configure_channel(
    request: TenantChannelCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    try:
        record = await service.configure_channel(
            tenant_id=expected_tenant_id,
            channel_type=request.channel_type,
            routing_address=request.routing_address,
            credentials=request.credentials,
            webhook_secret=request.webhook_secret,
            status=request.status,
        )
    except TenantConfigurationError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "tenant_channel_configuration_failed"},
        ) from exc
    return TenantChannelConfigurationResponse.from_record(record)


@router.put(
    "/channels/{config_id}",
    response_model=TenantChannelConfigurationResponse,
)
async def update_channel(
    config_id: str,
    request: TenantChannelUpdateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    try:
        record = await service.update_channel(
            tenant_id=expected_tenant_id,
            config_id=as_channel_configuration_id(config_id),
            routing_address=request.routing_address,
            credentials=request.credentials,
            webhook_secret=request.webhook_secret,
            status=request.status,
        )
    except (ValueError, TenantConfigurationNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "channel_configuration_not_found"},
        ) from exc
    except TenantConfigurationError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "tenant_channel_update_failed"},
        ) from exc
    return TenantChannelConfigurationResponse.from_record(record)


@router.post(
    "/channels/{config_id}/verify",
    response_model=TenantChannelConfigurationResponse,
)
async def verify_channel(
    config_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    try:
        record = await service.verify_channel(
            tenant_id=expected_tenant_id,
            config_id=as_channel_configuration_id(config_id),
        )
    except (ValueError, TenantConfigurationNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "channel_configuration_not_found"},
        ) from exc
    return TenantChannelConfigurationResponse.from_record(record)


@router.get(
    "/channels",
    response_model=TenantChannelConfigurationPage,
)
async def list_channels(
    channel_type: TenantChannelType | None = Query(None),
    status_filter: TenantChannelStatus | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationPage:
    page = await service.list_channels(
        tenant_id=expected_tenant_id,
        channel_type=channel_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantChannelConfigurationPage(
        items=[
            TenantChannelConfigurationResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/knowledge",
    response_model=TenantKnowledgeDocumentResponse,
)
async def create_knowledge_document(
    request: TenantKnowledgeCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantKnowledgeDocumentResponse:
    record = await service.create_knowledge_document(
        tenant_id=expected_tenant_id,
        title=request.title,
        content=request.content,
        document_type=request.document_type,
        status=request.status,
        uploaded_by=_principal_or_400(authority),
    )
    return TenantKnowledgeDocumentResponse.from_record(record)


@router.put(
    "/knowledge/{document_id}",
    response_model=TenantKnowledgeDocumentResponse,
)
async def update_knowledge_document(
    document_id: str,
    request: TenantKnowledgeUpdateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantKnowledgeDocumentResponse:
    try:
        record = await service.update_knowledge_document(
            tenant_id=expected_tenant_id,
            document_id=as_knowledge_document_id(document_id),
            content=request.content,
            status=request.status,
            uploaded_by=_principal_or_400(authority),
        )
    except (ValueError, TenantConfigurationNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "knowledge_document_not_found"},
        ) from exc
    return TenantKnowledgeDocumentResponse.from_record(record)


@router.get(
    "/knowledge",
    response_model=TenantKnowledgeDocumentPage,
)
async def list_knowledge_documents(
    document_type: TenantKnowledgeDocumentType | None = Query(None),
    status_filter: TenantKnowledgeDocumentStatus | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantKnowledgeDocumentPage:
    page = await service.list_knowledge_documents(
        tenant_id=expected_tenant_id,
        document_type=document_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantKnowledgeDocumentPage(
        items=[
            TenantKnowledgeDocumentResponse.from_record(record) for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/policies",
    response_model=TenantGovernancePolicyResponse,
)
async def create_governance_policy(
    request: TenantGovernancePolicyCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantGovernancePolicyResponse:
    record = await service.create_governance_policy(
        tenant_id=expected_tenant_id,
        policy_type=request.policy_type,
        parameters=request.parameters,
        status=request.status,
        approved_by=_principal_or_400(authority),
        effective_from=request.effective_from,
    )
    return TenantGovernancePolicyResponse.from_record(record)


@router.put(
    "/policies/{policy_id}",
    response_model=TenantGovernancePolicyResponse,
)
async def update_governance_policy(
    policy_id: str,
    request: TenantGovernancePolicyUpdateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantGovernancePolicyResponse:
    try:
        record = await service.update_governance_policy(
            tenant_id=expected_tenant_id,
            policy_id=as_governance_policy_id(policy_id),
            parameters=request.parameters,
            status=request.status,
            approved_by=_principal_or_400(authority),
            effective_from=request.effective_from,
        )
    except (ValueError, TenantConfigurationNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "governance_policy_not_found"},
        ) from exc
    return TenantGovernancePolicyResponse.from_record(record)


@router.get(
    "/policies",
    response_model=TenantGovernancePolicyPage,
)
async def list_governance_policies(
    policy_type: str | None = Query(None),
    status_filter: TenantGovernancePolicyStatus | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantGovernancePolicyPage:
    page = await service.list_governance_policies(
        tenant_id=expected_tenant_id,
        policy_type=policy_type,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantGovernancePolicyPage(
        items=[
            TenantGovernancePolicyResponse.from_record(record) for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/execution-governance",
    response_model=TenantExecutionGovernanceResponse,
)
async def configure_execution_governance(
    request: TenantExecutionGovernanceCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantExecutionGovernanceResponse:
    record = await service.configure_execution_governance(
        tenant_id=expected_tenant_id,
        execution_quota=request.execution_quota,
        throughput_limit=request.throughput_limit,
        throughput_window_minutes=request.throughput_window_minutes,
        governance_budget_limit=request.governance_budget_limit,
        governance_budget_window_minutes=request.governance_budget_window_minutes,
        circuit_failure_threshold=request.circuit_failure_threshold,
        circuit_window_minutes=request.circuit_window_minutes,
        circuit_cooldown_minutes=request.circuit_cooldown_minutes,
        status=request.status,
        configured_by=_principal_or_400(authority),
        metadata=request.metadata,
    )
    return TenantExecutionGovernanceResponse.from_record(record)


@router.get(
    "/execution-governance",
    response_model=TenantExecutionGovernancePage,
)
async def list_execution_governance_configurations(
    status_filter: TenantExecutionGovernanceStatus | None = Query(
        None,
        alias="status",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantExecutionGovernancePage:
    page = await service.list_execution_governance_configurations(
        tenant_id=expected_tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantExecutionGovernancePage(
        items=[
            TenantExecutionGovernanceResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.get(
    "/execution-governance/circuit-breakers",
    response_model=TenantExecutionCircuitBreakerPage,
)
async def list_execution_circuit_breakers(
    state: TenantExecutionCircuitState | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantExecutionCircuitBreakerPage:
    page = await service.list_execution_circuit_breakers(
        tenant_id=expected_tenant_id,
        state=state,
        limit=limit,
        offset=offset,
    )
    return TenantExecutionCircuitBreakerPage(
        items=[
            TenantExecutionCircuitBreakerResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/topologies",
    response_model=TenantTopologyConfigurationResponse,
)
async def configure_topology(
    request: TenantTopologyConfigurationCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantTopologyConfigurationResponse:
    try:
        record = await service.configure_topology(
            tenant_id=expected_tenant_id,
            topology_name=request.topology_name,
            topology=request.topology,
            status=request.status,
            configured_by=_principal_or_400(authority),
        )
    except TenantTopologyCycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tenant_topology_cycle_detected"},
        ) from exc
    except TenantConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tenant_topology_configuration_invalid"},
        ) from exc
    return TenantTopologyConfigurationResponse.from_record(record)


@router.get(
    "/topologies",
    response_model=TenantTopologyConfigurationPage,
)
async def list_topology_configurations(
    topology_name: str | None = Query(None),
    status_filter: TenantTopologyStatus | None = Query(None, alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantTopologyConfigurationPage:
    page = await service.list_topology_configurations(
        tenant_id=expected_tenant_id,
        topology_name=topology_name,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantTopologyConfigurationPage(
        items=[
            TenantTopologyConfigurationResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


def _principal_or_400(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "principal_axis_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
