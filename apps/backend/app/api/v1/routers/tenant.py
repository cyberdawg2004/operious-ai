"""Tenant-owned configuration endpoints (Phase 2.5-A)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)

from app.api.v1.schemas.tenant import (
    TenantAdminProvisionRequest,
    TenantAdminProvisionResponse,
    TenantConfigChangeRequestCreateRequest,
    TenantConfigChangeRequestPage,
    TenantConfigChangeRequestRejectRequest,
    TenantConfigChangeRequestResponse,
    TenantChannelConfigurationPage,
    TenantChannelConfigurationResponse,
    TenantChannelCreateRequest,
    TenantSesSelfServiceRequest,
    TenantChannelUpdateRequest,
    TenantWhatsAppSelfServiceRequest,
    TenantConnectorConfigurationPage,
    TenantConnectorConfigurationResponse,
    TenantConnectorTestResponse,
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
    TenantKnowledgeUploadResponse,
    TenantLifecycleCreateRequest,
    TenantLifecyclePage,
    TenantLifecycleResponse,
    TenantTopologyConfigurationCreateRequest,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationResponse,
)
from app.dependencies.authority import (
    ERROR_CODE_CAPABILITY_REQUIRED,
    TENANT_CHANNEL_ADMIN_CAPABILITY,
    TENANT_CONNECTOR_APPROVE_CAPABILITY,
    TENANT_CONNECTOR_WRITE_CAPABILITY,
    TENANT_CONFIG_APPROVE_CAPABILITY,
    TENANT_CONFIG_READ_CAPABILITY,
    TENANT_CONFIG_WRITE_CAPABILITY,
    TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY,
    TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TENANT_POLICY_WRITE_CAPABILITY,
    TENANT_TOPOLOGY_WRITE_CAPABILITY,
    require_authority,
    require_capability,
    require_config_apply_authorization_for,
    require_platform_tenant_admin,
    request_tenant_scope_opt,
    require_tenant_connector_read,
    require_tenant_scope,
)
from app.dependencies.services import (
    get_tenant_config_change_request_service,
    get_tenant_configuration_service,
    get_tenant_lifecycle_service,
)
from app.identity import AuthorityContext
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_configuration_service import (
    TenantConfigurationService,
)
from app.services.tenant_lifecycle_service import TenantLifecycleService
from app.tenant.change_requests import (
    TenantConfigChangeRequestError,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestNotFoundError,
    TenantConfigChangeRequestSeparationError,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
    TenantConfigChangeRequestValidationError,
)
from app.tenant.channel_self_service import (
    TenantChannelSelfServicePayload,
    build_ses_self_service_payload,
    build_whatsapp_self_service_payload,
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
    TenantConfigurationDualControlRequiredError,
    TenantConfigurationError,
    TenantConfigurationNotFoundError,
    TenantTopologyCycleError,
)
from app.core.config import get_settings
from app.tenant.file_ingestion import (
    KnowledgeUploadEmptyTextError,
    KnowledgeUploadTypeError,
    KnowledgeUploadUnparsableError,
    parse_uploaded_document,
)
from app.tenant.identity import (
    as_channel_configuration_id,
    derive_channel_configuration_id,
    as_governance_policy_id,
    as_knowledge_document_id,
)
from app.tenant.lifecycle import (
    TenantAdminProvisioningError,
    TenantAdminProvisioningUnavailableError,
    TenantAlreadyExistsError,
    TenantLifecycleError,
    TenantNotFoundError,
)
from app.api.v1.schemas.mcp import (
    McpOAuthCallbackParams,
    McpOAuthStartRequest,
    McpOAuthStartResponse,
    McpServerRegisterRequest,
    McpToolManifestResponse,
    McpToolPreviewRequest,
)
from app.core.ssrf import SSRFValidationError

router = APIRouter(tags=["tenant"])
require_platform_lifecycle_admin = require_platform_tenant_admin
require_tenant_config_read = require_capability(TENANT_CONFIG_READ_CAPABILITY)
require_tenant_config_write = require_capability(TENANT_CONFIG_WRITE_CAPABILITY)
require_tenant_connector_write = require_capability(TENANT_CONNECTOR_WRITE_CAPABILITY)
require_tenant_config_approve = require_capability(TENANT_CONFIG_APPROVE_CAPABILITY)
require_tenant_connector_config_read = require_tenant_connector_read
require_tenant_channel_direct_apply = require_config_apply_authorization_for(
    TENANT_CHANNEL_ADMIN_CAPABILITY
)
require_tenant_knowledge_direct_apply = require_config_apply_authorization_for(
    TENANT_KNOWLEDGE_WRITE_CAPABILITY
)
require_tenant_policy_direct_apply = require_config_apply_authorization_for(
    TENANT_POLICY_WRITE_CAPABILITY
)
require_tenant_topology_direct_apply = require_config_apply_authorization_for(
    TENANT_TOPOLOGY_WRITE_CAPABILITY
)
require_tenant_execution_governance_direct_apply = (
    require_config_apply_authorization_for(
        TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY
    )
)

_CHANGE_REQUEST_DOMAIN_CAPABILITIES: Final[dict[TenantConfigChangeType, str]] = {
    TenantConfigChangeType.CHANNEL: TENANT_CHANNEL_ADMIN_CAPABILITY,
    TenantConfigChangeType.KNOWLEDGE: TENANT_KNOWLEDGE_WRITE_CAPABILITY,
    TenantConfigChangeType.POLICY: TENANT_POLICY_WRITE_CAPABILITY,
    TenantConfigChangeType.TOPOLOGY: TENANT_TOPOLOGY_WRITE_CAPABILITY,
    TenantConfigChangeType.EXECUTION_GOVERNANCE: (
        TENANT_EXECUTION_GOVERNANCE_WRITE_CAPABILITY
    ),
    TenantConfigChangeType.CONNECTOR: TENANT_CONNECTOR_WRITE_CAPABILITY,
    TenantConfigChangeType.CREDENTIAL_UPDATE: TENANT_CONNECTOR_WRITE_CAPABILITY,
}

# Connector config changes require a domain-specific approve capability instead of
# the generic tenant.config.approve, enforcing connector-approval as a separate duty.
_CHANGE_REQUEST_APPROVE_CAPABILITIES: Final[dict[TenantConfigChangeType, str]] = {
    TenantConfigChangeType.CONNECTOR: TENANT_CONNECTOR_APPROVE_CAPABILITY,
}

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25
_OMS_CREDENTIAL_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"refund.request", "warranty.claim", "replacement.order"}
)


@router.post(
    "/lifecycle/tenants",
    response_model=TenantLifecycleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_tenant_lifecycle(
    request: TenantLifecycleCreateRequest,
    authority: AuthorityContext = Depends(require_platform_lifecycle_admin),
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: TenantLifecycleService = Depends(get_tenant_lifecycle_service),
) -> TenantLifecycleResponse:
    try:
        record = await service.create_tenant(
            tenant_id=request.tenant_id,
            created_by=_principal_or_400(authority),
        )
    except (TenantLifecycleError, ValueError) as exc:
        raise _tenant_lifecycle_http_error(exc) from exc
    return TenantLifecycleResponse.from_record(record)


@router.get(
    "/lifecycle/tenants",
    response_model=TenantLifecyclePage,
)
async def list_tenant_lifecycle(
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    _authority: AuthorityContext = Depends(require_platform_lifecycle_admin),
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: TenantLifecycleService = Depends(get_tenant_lifecycle_service),
) -> TenantLifecyclePage:
    page = await service.list_tenants(limit=limit, offset=offset)
    return TenantLifecyclePage.from_page(page)


@router.post(
    "/lifecycle/tenants/{tenant_id}/admins",
    response_model=TenantAdminProvisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def provision_tenant_admin(
    tenant_id: str,
    request: TenantAdminProvisionRequest,
    authority: AuthorityContext = Depends(require_platform_lifecycle_admin),
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: TenantLifecycleService = Depends(get_tenant_lifecycle_service),
) -> TenantAdminProvisionResponse:
    try:
        record = await service.provision_tenant_config_admin(
            tenant_id=tenant_id,
            email=request.email,
            provisioned_by=_principal_or_400(authority),
        )
    except (TenantLifecycleError, ValueError) as exc:
        raise _tenant_lifecycle_http_error(exc) from exc
    return TenantAdminProvisionResponse.from_record(record)


@router.post(
    "/config/change-requests",
    response_model=TenantConfigChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def propose_config_change_request(
    request: TenantConfigChangeRequestCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    _require_change_request_domain_capability(
        change_type=request.change_type,
        authority=authority,
    )
    try:
        record = await service.propose(
            tenant_id=expected_tenant_id,
            change_type=request.change_type,
            payload=request.payload,
            proposed_by=_principal_or_400(authority),
        )
    except TenantConfigChangeRequestError as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.get(
    "/config/change-requests",
    response_model=TenantConfigChangeRequestPage,
)
async def list_config_change_requests(
    status_filter: TenantConfigChangeRequestStatus | None = Query(
        None,
        alias="status",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _reader: AuthorityContext = Depends(require_tenant_config_read),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestPage:
    page = await service.list(
        expected_tenant_id=expected_tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantConfigChangeRequestPage.from_page(page)


@router.post(
    "/config/change-requests/{change_request_id}/approve",
    response_model=TenantConfigChangeRequestResponse,
)
async def approve_config_change_request(
    change_request_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_authority),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    try:
        existing = await service.get(
            change_request_id=change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    _require_change_request_approve_capability(
        change_type=existing.change_type, authority=authority
    )
    try:
        record = await service.approve(
            change_request_id=change_request_id,
            approved_by=_principal_or_400(authority),
            expected_tenant_id=expected_tenant_id,
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.post(
    "/config/change-requests/{change_request_id}/reject",
    response_model=TenantConfigChangeRequestResponse,
)
async def reject_config_change_request(
    change_request_id: str,
    request: TenantConfigChangeRequestRejectRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_config_approve),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    try:
        record = await service.reject(
            change_request_id=change_request_id,
            rejected_by=_principal_or_400(authority),
            reason=request.reason,
            expected_tenant_id=expected_tenant_id,
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.post(
    "/config/change-requests/{change_request_id}/apply",
    response_model=TenantConfigChangeRequestResponse,
)
async def apply_config_change_request(
    change_request_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _approver: AuthorityContext = Depends(require_tenant_config_approve),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    try:
        record = await service.apply(
            change_request_id=change_request_id,
            expected_tenant_id=expected_tenant_id,
            applied_by=_principal_or_400(_approver),
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.post(
    "/config/change-requests/{change_request_id}/revoke",
    response_model=TenantConfigChangeRequestResponse,
)
async def revoke_config_change_request(
    change_request_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_config_approve),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    """Revoke an APPROVED change request before it is applied.

    Requires the ``tenant.config.approve`` capability. Any approved request
    that has not yet been applied can be revoked; APPLIED, REJECTED, and
    already-REVOKED requests return 409.
    """
    try:
        record = await service.revoke(
            change_request_id=change_request_id,
            expected_tenant_id=expected_tenant_id,
            revoked_by=_principal_or_400(authority),
        )
    except (ValueError, TenantConfigChangeRequestError) as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.post(
    "/channels",
    response_model=TenantChannelConfigurationResponse,
)
async def configure_channel(
    request: TenantChannelCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
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
            self_service_config=request.self_service_config,
        )
    except TenantConfigurationError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "tenant_channel_configuration_failed"},
        ) from exc
    return TenantChannelConfigurationResponse.from_record(record)


@router.post(
    "/channels/whatsapp/self-service",
    response_model=TenantChannelConfigurationResponse,
)
async def configure_whatsapp_self_service_channel(
    request: TenantWhatsAppSelfServiceRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    return await _apply_whatsapp_self_service_channel(
        request=request,
        expected_tenant_id=expected_tenant_id,
        service=service,
        require_existing=False,
    )


@router.put(
    "/channels/whatsapp/self-service",
    response_model=TenantChannelConfigurationResponse,
)
async def update_whatsapp_self_service_channel(
    request: TenantWhatsAppSelfServiceRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    return await _apply_whatsapp_self_service_channel(
        request=request,
        expected_tenant_id=expected_tenant_id,
        service=service,
        require_existing=True,
    )


@router.post(
    "/channels/email/self-service",
    response_model=TenantChannelConfigurationResponse,
)
async def configure_email_self_service_channel(
    request: TenantSesSelfServiceRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    return await _apply_ses_self_service_channel(
        request=request,
        expected_tenant_id=expected_tenant_id,
        service=service,
        require_existing=False,
    )


@router.put(
    "/channels/email/self-service",
    response_model=TenantChannelConfigurationResponse,
)
async def update_email_self_service_channel(
    request: TenantSesSelfServiceRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantChannelConfigurationResponse:
    return await _apply_ses_self_service_channel(
        request=request,
        expected_tenant_id=expected_tenant_id,
        service=service,
        require_existing=True,
    )


@router.get(
    "/connectors",
    response_model=TenantConnectorConfigurationPage,
)
async def list_connector_configurations(
    connector_type: str | None = Query(None),
    tool_name: str | None = Query(None),
    status_filter: str | None = Query("active", alias="status"),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _reader: AuthorityContext = Depends(require_tenant_connector_config_read),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantConnectorConfigurationPage:
    page = await service.list_connector_configurations(
        tenant_id=expected_tenant_id,
        connector_type=connector_type,
        tool_name=tool_name,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TenantConnectorConfigurationPage(
        items=[
            TenantConnectorConfigurationResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.get(
    "/connectors/{tool_name}",
    response_model=TenantConnectorConfigurationPage,
)
async def list_connector_configuration_history(
    tool_name: str,
    connector_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(_MAX_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _reader: AuthorityContext = Depends(require_tenant_connector_config_read),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantConnectorConfigurationPage:
    page = await service.list_connector_configurations(
        tenant_id=expected_tenant_id,
        connector_type=connector_type,
        tool_name=tool_name,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    if page.total == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_connector_configuration_not_found"},
        )
    return TenantConnectorConfigurationPage(
        items=[
            TenantConnectorConfigurationResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


@router.post(
    "/{tenant_id}/connectors/{tool_name}/test",
    response_model=TenantConnectorTestResponse,
)
async def test_connector_configuration(
    tenant_id: str,
    tool_name: str,
    probe_http: bool = Query(False),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _writer: AuthorityContext = Depends(require_tenant_connector_write),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantConnectorTestResponse:
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_connector_configuration_not_found"},
        )
    try:
        result = await service.test_connector_connection(
            tenant_id=expected_tenant_id,
            tool_name=tool_name,
            probe_http=probe_http,
        )
    except TenantConfigurationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_connector_configuration_not_found"},
        ) from exc
    return TenantConnectorTestResponse(
        reachable=result.reachable,
        config_valid=result.config_valid,
        validated_host=result.validated_host,
        tls_verified=result.tls_verified,
        http_probe=result.http_probe,
    )


@router.post(
    "/{tenant_id}/connectors/{tool_name}/credentials",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def propose_connector_credentials(
    tenant_id: str,
    tool_name: str,
    credentials: dict[str, object] = Body(...),
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_connector_write),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> Response:
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_connector_configuration_not_found"},
        )
    principal = _principal_or_400(authority)
    try:
        if tool_name in _OMS_CREDENTIAL_TOOL_NAMES:
            # Legacy OMS path: credential stored in tenant_channel_configurations.
            await service.propose_oms_credential_update(
                tenant_id=expected_tenant_id,
                credentials=credentials,
                proposed_by=principal,
            )
        else:
            # Generic path: per-connector credential store.
            # Derive connector_id from tool_name: "account.freeze" → "account",
            # "service.suspend" → "service", "myconn" → "myconn".
            connector_id = (
                tool_name[: tool_name.rfind(".")] if "." in tool_name else tool_name
            )
            await service.propose_connector_credential(
                tenant_id=expected_tenant_id,
                connector_id=connector_id,
                credentials=credentials,
                proposed_by=principal,
            )
    except TenantConfigChangeRequestError as exc:
        raise _change_request_http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/channels/{config_id}",
    response_model=TenantChannelConfigurationResponse,
)
async def update_channel(
    config_id: str,
    request: TenantChannelUpdateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
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
            self_service_config=request.self_service_config,
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
    _direct_apply: AuthorityContext = Depends(require_tenant_channel_direct_apply),
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
    authority: AuthorityContext = Depends(require_tenant_knowledge_direct_apply),
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
    authority: AuthorityContext = Depends(require_tenant_knowledge_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantKnowledgeDocumentResponse:
    try:
        record = await service.update_knowledge_document(
            tenant_id=expected_tenant_id,
            document_id=as_knowledge_document_id(document_id),
            content=request.content,
            status=request.status,
            uploaded_by=_principal_or_400(authority),
            review_status=request.review_status,
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
    "/knowledge/uploads",
    response_model=TenantKnowledgeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1),
    document_type: str = Form(...),
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_capability(TENANT_KNOWLEDGE_WRITE_CAPABILITY)),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
    change_request_service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantKnowledgeUploadResponse:
    settings = get_settings()
    max_bytes = settings.KNOWLEDGE_UPLOAD_MAX_BYTES

    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "knowledge_upload_too_large",
                "max_bytes": max_bytes,
            },
        )

    filename = file.filename or "upload"
    try:
        canonical_type, extracted_text = parse_uploaded_document(
            filename=filename,
            raw_bytes=raw,
        )
    except KnowledgeUploadTypeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "knowledge_upload_type_rejected", "detail": str(exc)},
        ) from exc
    except (KnowledgeUploadUnparsableError, KnowledgeUploadEmptyTextError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "knowledge_upload_unparsable", "detail": str(exc)},
        ) from exc

    principal = _principal_or_400(authority)
    now = datetime.now(tz=timezone.utc)
    upload_id = await service.create_knowledge_upload(
        tenant_id=expected_tenant_id,
        filename=filename,
        content_type=canonical_type,
        raw_content=raw,
        uploaded_by=principal,
        created_at=now,
    )

    try:
        doc_type = TenantKnowledgeDocumentType(document_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "knowledge_upload_invalid_document_type"},
        ) from exc

    change_request = await change_request_service.propose(
        tenant_id=expected_tenant_id,
        change_type=TenantConfigChangeType.KNOWLEDGE,
        payload={
            "operation": "create",
            "title": title,
            "content": extracted_text,
            "document_type": doc_type.value,
        },
        proposed_by=principal,
    )
    return TenantKnowledgeUploadResponse(
        upload_id=str(upload_id),
        tenant_id=expected_tenant_id,
        filename=filename,
        content_type=canonical_type,
        byte_size=len(raw),
        uploaded_by=principal,
        created_at=now.isoformat(),
        change_request_id=str(change_request.change_request_id),
    )


@router.post(
    "/policies",
    response_model=TenantGovernancePolicyResponse,
)
async def create_governance_policy(
    request: TenantGovernancePolicyCreateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_policy_direct_apply),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> TenantGovernancePolicyResponse:
    try:
        record = await service.create_governance_policy(
            tenant_id=expected_tenant_id,
            policy_type=request.policy_type,
            parameters=request.parameters,
            status=request.status,
            approved_by=_principal_or_400(authority),
            effective_from=request.effective_from,
        )
    except TenantConfigurationDualControlRequiredError as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "dual_control_required_for_policy_type",
                "policy_type": request.policy_type,
            },
        ) from exc
    return TenantGovernancePolicyResponse.from_record(record)


@router.put(
    "/policies/{policy_id}",
    response_model=TenantGovernancePolicyResponse,
)
async def update_governance_policy(
    policy_id: str,
    request: TenantGovernancePolicyUpdateRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_policy_direct_apply),
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
    except TenantConfigurationDualControlRequiredError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "dual_control_required_for_policy_type"},
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
    authority: AuthorityContext = Depends(
        require_tenant_execution_governance_direct_apply
    ),
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
    authority: AuthorityContext = Depends(require_tenant_topology_direct_apply),
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


async def _apply_whatsapp_self_service_channel(
    *,
    request: TenantWhatsAppSelfServiceRequest,
    expected_tenant_id: str,
    service: TenantConfigurationService,
    require_existing: bool,
) -> TenantChannelConfigurationResponse:
    config_id = derive_channel_configuration_id(
        tenant_id=expected_tenant_id,
        channel_type=TenantChannelType.WHATSAPP,
    )
    existing = await service.get_channel_configuration(
        tenant_id=expected_tenant_id,
        config_id=config_id,
    )
    if require_existing and existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "channel_configuration_not_found"},
        )
    existing_credentials = (
        await service.load_channel_credentials(
            tenant_id=expected_tenant_id,
            channel_type=TenantChannelType.WHATSAPP,
        )
        if existing is not None
        else None
    )
    try:
        payload = build_whatsapp_self_service_payload(
            request.model_dump(by_alias=True, exclude_none=True),
            existing_channel=existing,
            existing_credentials=existing_credentials,
        )
    except (TenantConfigurationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tenant_whatsapp_self_service_invalid"},
        ) from exc
    return await _persist_self_service_channel(
        payload=payload,
        expected_tenant_id=expected_tenant_id,
        existing=existing is not None,
        service=service,
    )


async def _apply_ses_self_service_channel(
    *,
    request: TenantSesSelfServiceRequest,
    expected_tenant_id: str,
    service: TenantConfigurationService,
    require_existing: bool,
) -> TenantChannelConfigurationResponse:
    config_id = derive_channel_configuration_id(
        tenant_id=expected_tenant_id,
        channel_type=TenantChannelType.EMAIL,
    )
    existing = await service.get_channel_configuration(
        tenant_id=expected_tenant_id,
        config_id=config_id,
    )
    if require_existing and existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "channel_configuration_not_found"},
        )
    existing_credentials = (
        await service.load_channel_credentials(
            tenant_id=expected_tenant_id,
            channel_type=TenantChannelType.EMAIL,
        )
        if existing is not None
        else None
    )
    try:
        payload = build_ses_self_service_payload(
            request.model_dump(exclude_none=True),
            existing_channel=existing,
            existing_credentials=existing_credentials,
        )
    except (TenantConfigurationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tenant_ses_self_service_invalid"},
        ) from exc
    return await _persist_self_service_channel(
        payload=payload,
        expected_tenant_id=expected_tenant_id,
        existing=existing is not None,
        service=service,
    )


async def _persist_self_service_channel(
    *,
    payload: TenantChannelSelfServicePayload,
    expected_tenant_id: str,
    existing: bool,
    service: TenantConfigurationService,
) -> TenantChannelConfigurationResponse:
    try:
        if existing:
            record = await service.update_channel(
                tenant_id=expected_tenant_id,
                config_id=derive_channel_configuration_id(
                    tenant_id=expected_tenant_id,
                    channel_type=payload.channel_type,
                ),
                routing_address=payload.routing_address,
                credentials=payload.credentials,
                webhook_secret=payload.webhook_secret,
                status=payload.status,
                self_service_config=payload.self_service_config,
                last_validation_error=payload.last_validation_error,
                validation_evidence=payload.validation_evidence,
            )
        else:
            if payload.credentials is None:
                raise TenantConfigurationError(
                    "self-service channel credentials are required on create"
                )
            if payload.webhook_secret is None:
                raise TenantConfigurationError(
                    "self-service channel webhook secret is required on create"
                )
            record = await service.configure_channel(
                tenant_id=expected_tenant_id,
                channel_type=payload.channel_type,
                routing_address=payload.routing_address,
                credentials=payload.credentials,
                webhook_secret=payload.webhook_secret,
                status=payload.status,
                self_service_config=payload.self_service_config,
                last_validation_error=payload.last_validation_error,
                validation_evidence=payload.validation_evidence,
            )
    except TenantConfigurationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "channel_configuration_not_found"},
        ) from exc
    except TenantConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "tenant_channel_self_service_failed"},
        ) from exc
    return TenantChannelConfigurationResponse.from_record(record)


def _require_change_request_domain_capability(
    *,
    change_type: TenantConfigChangeType,
    authority: AuthorityContext,
) -> None:
    capability = _CHANGE_REQUEST_DOMAIN_CAPABILITIES[change_type]
    if capability not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_CAPABILITY_REQUIRED,
                "capability": capability,
            },
        )


def _require_change_request_approve_capability(
    *,
    change_type: TenantConfigChangeType,
    authority: AuthorityContext,
) -> None:
    capability = _CHANGE_REQUEST_APPROVE_CAPABILITIES.get(
        change_type, TENANT_CONFIG_APPROVE_CAPABILITY
    )
    if capability not in authority.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": ERROR_CODE_CAPABILITY_REQUIRED,
                "capability": capability,
            },
        )


def _change_request_http_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, TenantConfigChangeRequestNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_config_change_request_not_found"},
        )
    if isinstance(exc, TenantConfigChangeRequestSeparationError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "tenant_config_approver_must_differ"},
        )
    if isinstance(exc, TenantConfigChangeRequestValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "tenant_config_change_request_invalid",
                "message": str(exc),
            },
        )
    if isinstance(exc, TenantConfigChangeRequestLifecycleError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "tenant_config_change_request_lifecycle_error"},
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "tenant_config_change_request_invalid",
                "message": str(exc),
            },
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "tenant_config_change_request_failed"},
    )


def _tenant_lifecycle_http_error(exc: BaseException) -> HTTPException:
    if isinstance(exc, TenantAlreadyExistsError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "tenant_already_exists"},
        )
    if isinstance(exc, TenantNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_not_found"},
        )
    if isinstance(exc, TenantAdminProvisioningUnavailableError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "tenant_admin_provisioning_unavailable"},
        )
    if isinstance(exc, TenantAdminProvisioningError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "tenant_admin_provisioning_failed"},
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "tenant_lifecycle_invalid"},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "tenant_lifecycle_failed"},
    )


@router.post(
    "/{tenant_id}/mcp/preview-tools",
    response_model=McpToolManifestResponse,
    status_code=status.HTTP_200_OK,
)
async def preview_mcp_tools(
    tenant_id: str,
    request: McpToolPreviewRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _reader: AuthorityContext = Depends(require_tenant_connector_config_read),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> McpToolManifestResponse:
    """Fetch a live tool manifest from a raw MCP endpoint URL (pre-registration preview).

    Does NOT require an existing ConnectorConfigRecord. Used by the UI add-server
    flow to show tools before the server is registered. The URL must be a public HTTPS
    address — private/link-local/metadata IPs are rejected by the SSRF guard.
    """
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_not_found"},
        )
    mcp_url = request.endpoint_url.rstrip("/") + "/mcp"
    try:
        tools = await service.fetch_mcp_tools(mcp_url, timeout=request.timeout_seconds)
    except SSRFValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoint_ssrf_rejected", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "mcp_server_unreachable",
                "message": f"{type(exc).__name__}: could not fetch tool manifest",
            },
        ) from exc

    return McpToolManifestResponse(mcp_server_id="preview", tools=tools)


@router.post(
    "/{tenant_id}/mcp/servers",
    response_model=TenantConfigChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_mcp_server(
    tenant_id: str,
    request: McpServerRegisterRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_tenant_connector_write),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> TenantConfigChangeRequestResponse:
    """Propose an MCP_SERVER change-request.

    Stores the server registration (endpoint URL, tool manifest, execution policies)
    as a dual-control change request. Must be approved + applied before the server
    is used in the agent's tool registry.
    """
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_not_found"},
        )
    try:
        record = await service.propose(
            tenant_id=expected_tenant_id,
            change_type=TenantConfigChangeType.MCP_SERVER,
            payload={
                "mcp_server_id": request.mcp_server_id,
                "endpoint_url": request.endpoint_url,
                "mcp_tools": request.mcp_tools,
                **({"oauth_config": request.oauth_config} if request.oauth_config else {}),
                "timeout_seconds": request.timeout_seconds,
            },
            proposed_by=_principal_or_400(authority),
        )
    except TenantConfigChangeRequestError as exc:
        raise _change_request_http_error(exc) from exc
    return TenantConfigChangeRequestResponse.from_record(record)


@router.get(
    "/{tenant_id}/mcp/servers/{mcp_server_id}/tools",
    response_model=McpToolManifestResponse,
)
async def list_mcp_server_tools(
    tenant_id: str,
    mcp_server_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _reader: AuthorityContext = Depends(require_tenant_connector_config_read),
    service: TenantConfigurationService = Depends(get_tenant_configuration_service),
) -> McpToolManifestResponse:
    """Fetch a live tool manifest from the configured MCP server via tools/list.

    Calls the MCP server's /mcp endpoint using the MCP Python SDK, returning
    the current tool names, descriptions, and input schemas.
    """
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_not_found"},
        )
    # Load the active connector config for this MCP server.
    connector_page = await service.list_connector_configurations(
        tenant_id=expected_tenant_id,
        connector_type="mcp_server",
        tool_name=mcp_server_id,
        status="active",
        limit=1,
        offset=0,
    )
    if connector_page.total == 0 or not connector_page.items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "mcp_server_not_found"},
        )
    server_record = connector_page.items[0]
    # Re-validate the stored endpoint_template at fetch time (TOCTOU guard: a
    # stored URL could have been mutated between validation and use).
    server_url = f"{server_record.endpoint_template.rstrip('/')}/mcp"

    try:
        tools = await service.fetch_mcp_tools(server_url, timeout=15.0)
    except SSRFValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "endpoint_ssrf_rejected", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "mcp_server_unreachable",
                "message": f"{type(exc).__name__}: could not fetch tool manifest",
            },
        ) from exc

    return McpToolManifestResponse(mcp_server_id=mcp_server_id, tools=tools)


@router.post(
    "/{tenant_id}/mcp/oauth/start",
    response_model=McpOAuthStartResponse,
    status_code=status.HTTP_200_OK,
)
async def mcp_oauth_start(
    tenant_id: str,
    request: McpOAuthStartRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    _writer: AuthorityContext = Depends(require_tenant_connector_write),
) -> McpOAuthStartResponse:
    """Initiate an OAuth authorization code + PKCE dance for an MCP server.

    Generates a PKCE code_verifier/challenge and a HMAC-bound state token,
    stores the OAuth context in Redis (TTL=600s), and returns the authorization URL
    the operator should redirect the user to.
    """
    if tenant_id != expected_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "tenant_not_found"},
        )
    import base64
    import hashlib
    import hmac
    import os
    import json as _json

    from app.core.config import get_settings
    from app.core.redis import get_redis_client

    settings = get_settings()
    redis = get_redis_client()

    # Generate PKCE code_verifier (43-128 chars, URL-safe base64).
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    # Generate state token and HMAC-bind it to the tenant_id.
    raw_state = base64.urlsafe_b64encode(os.urandom(24)).rstrip(b"=").decode()
    _secret = settings.MCP_OAUTH_STATE_SECRET
    state_hmac = hmac.new(
        _secret.encode(),
        f"{tenant_id}:{raw_state}".encode(),
        "sha256",
    ).hexdigest()
    state_token = f"{raw_state}.{state_hmac}"

    # Store in Redis with TTL=600s.  oauth_config is serialised as a plain dict
    # so the callback can deserialise it without importing the schema.
    oauth_cfg = request.oauth_config
    oauth_state: dict[str, object] = {
        "tenant_id": tenant_id,
        "mcp_server_id": request.mcp_server_id,
        "code_verifier": code_verifier,
        "oauth_config": oauth_cfg.model_dump(),
    }
    redis_key = f"mcp:oauth:state:{state_token}"
    await redis.setex(redis_key, 600, _json.dumps(oauth_state))

    # Build authorization URL with PKCE.
    scopes_str = " ".join(oauth_cfg.scopes)
    redirect_uri = oauth_cfg.redirect_uri
    client_id = oauth_cfg.client_id
    auth_endpoint = oauth_cfg.auth_endpoint

    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes_str,
        "state": state_token,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    authorization_url = f"{auth_endpoint}?{urlencode(params)}"

    return McpOAuthStartResponse(
        authorization_url=authorization_url,
        state_token=state_token,
    )


@router.get(
    "/mcp/oauth/callback",
    status_code=status.HTTP_302_FOUND,
)
async def mcp_oauth_callback(
    params: McpOAuthCallbackParams = Depends(),
    _tenant_scope: str | None = Depends(request_tenant_scope_opt),
    service: TenantConfigChangeRequestService = Depends(
        get_tenant_config_change_request_service
    ),
) -> Response:
    """OAuth callback handler (tenant-agnostic path; tenant_id is in Redis state).

    Validates the state HMAC, retrieves the OAuth context from Redis, exchanges
    the authorization code + PKCE verifier for tokens (server-to-server), encrypts
    the token via OPCRED2, and proposes an MCP_OAUTH_TOKEN change-request.
    """
    import hmac
    import json as _json

    from app.core.config import get_settings
    from app.core.http import get_shared_http_client
    from app.core.redis import get_redis_client

    settings = get_settings()
    redis = get_redis_client()
    _secret = settings.MCP_OAUTH_STATE_SECRET

    # Validate HMAC on the state token.
    state_token = params.state
    if "." not in state_token:
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=invalid_state"},
        )
    raw_state, received_hmac = state_token.rsplit(".", 1)

    # Retrieve from Redis first (we need tenant_id for HMAC verification).
    redis_key = f"mcp:oauth:state:{state_token}"
    raw_value = await redis.get(redis_key)
    if raw_value is None:
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=state_expired"},
        )
    oauth_state = _json.loads(raw_value)
    tenant_id: str = oauth_state["tenant_id"]

    # Verify HMAC (binding state to tenant_id prevents cross-tenant replay).
    expected_hmac = hmac.new(
        _secret.encode(),
        f"{tenant_id}:{raw_state}".encode(),
        "sha256",
    ).hexdigest()
    if not hmac.compare_digest(received_hmac, expected_hmac):
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=invalid_state"},
        )

    # Delete from Redis — single use.
    await redis.delete(redis_key)

    mcp_server_id: str = oauth_state["mcp_server_id"]
    code_verifier: str = oauth_state["code_verifier"]
    oauth_config: dict[str, object] = oauth_state["oauth_config"]

    # Exchange code for tokens (server-to-server call).
    token_endpoint = str(oauth_config.get("token_endpoint", ""))
    redirect_uri = str(oauth_config.get("redirect_uri", ""))
    client_id = str(oauth_config.get("client_id", ""))
    client_secret = str(oauth_config.get("client_secret", ""))

    # SSRF guard on token_endpoint — re-validate even though the start
    # endpoint already validated it, to cover pre-schema Redis state.
    import asyncio as _asyncio
    from functools import partial as _partial
    from app.core.ssrf import SSRFValidationError as _SSRFErr, validate_public_https_url as _ssrf
    try:
        _loop = _asyncio.get_running_loop()
        _validated_token = await _loop.run_in_executor(
            None, _partial(_ssrf, token_endpoint, allowed_hosts=())
        )
    except _SSRFErr:
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=token_endpoint_rejected"},
        )

    import httpx as _httpx
    from app.core.ssrf import PinnedIPAsyncHTTPTransport as _PinnedTransport
    _pinned_transport = _PinnedTransport(pinned_ip=_validated_token.pinned_ip)

    try:
        async with _httpx.AsyncClient(
            transport=_pinned_transport,
            follow_redirects=False,
            timeout=15.0,
        ) as _http:
            token_response = await _http.post(
                token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": params.code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
        if token_response.status_code != 200:
            return Response(
                status_code=status.HTTP_302_FOUND,
                headers={
                    "Location": (
                        f"/connectors?oauth=error"
                        f"&reason=token_exchange_failed"
                        f"&status={token_response.status_code}"
                    )
                },
            )
        token_data = token_response.json()
    except Exception:  # noqa: BLE001
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=token_exchange_error"},
        )

    # Store the token via propose_connector_credential (encrypted via OPCRED2).
    # The token_data dict is the full OAuth response (access_token, refresh_token, etc.)
    try:
        await service.propose_connector_credential(
            tenant_id=tenant_id,
            connector_id=mcp_server_id,
            credentials=token_data,
            proposed_by="oauth_callback",
        )
    except TenantConfigChangeRequestError:
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/connectors?oauth=error&reason=credential_store_failed"},
        )

    return Response(
        status_code=status.HTTP_302_FOUND,
        headers={
            "Location": (
                f"/connectors?oauth=success&mcp_server_id={mcp_server_id}"
            )
        },
    )


__all__ = ["router"]
