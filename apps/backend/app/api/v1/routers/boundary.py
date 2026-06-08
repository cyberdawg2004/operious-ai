"""Boundary read endpoints — v1 transport layer (PR-D6).

Four read endpoints across the two apex record types:

* ``GET /ingress/{ingress_id}`` — one ingress record by id.
* ``GET /ingress``              — paginated ingress list.
* ``GET /egress/{egress_id}``   — one egress record by id.
* ``GET /egress``               — paginated egress list.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas.boundary import (
    BoundaryEgressPage,
    BoundaryEgressResponse,
    BoundaryIngressPage,
    BoundaryIngressResponse,
    WhatsAppCustomerReplySendRequest,
    WhatsAppCustomerReplySendResponse,
    WorkOrderFulfillmentCallbackRequest,
    WorkOrderFulfillmentReceiptResponse,
)
from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
)
from app.boundary.persistence import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryPersistenceProtocol,
)
from app.dependencies.authority import (
    require_tenant_actions_approve,
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_boundary_repository
from app.dependencies.services import get_work_order_fulfillment_receipt_service
from app.dependencies.services import get_whatsapp_customer_reply_send_service
from app.services.work_order_fulfillment_receipt_service import (
    WorkOrderFulfillmentReceiptError,
    WorkOrderFulfillmentReceiptService,
)
from app.services.whatsapp_customer_reply_service import (
    WhatsAppCustomerReplyConfigurationError,
    WhatsAppCustomerReplyGovernanceError,
    WhatsAppCustomerReplyNotFoundError,
    WhatsAppCustomerReplyProviderError,
    WhatsAppCustomerReplySendService,
)

router = APIRouter(tags=["boundary"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.post(
    "/work-orders/fulfillment",
    response_model=WorkOrderFulfillmentReceiptResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def record_work_order_fulfillment(
    payload: WorkOrderFulfillmentCallbackRequest,
    request: Request,
    service: WorkOrderFulfillmentReceiptService = Depends(
        get_work_order_fulfillment_receipt_service
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> WorkOrderFulfillmentReceiptResponse:
    try:
        receipt = await service.record_callback(
            expected_tenant_id=expected_tenant_id,
            payload=payload.model_dump(mode="json"),
            headers={str(k): str(v) for k, v in request.headers.items()},
            request_path=str(request.url.path),
        )
    except WorkOrderFulfillmentReceiptError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "work_order_fulfillment_callback_rejected",
                "reason": str(exc),
            },
        ) from exc
    return WorkOrderFulfillmentReceiptResponse(
        ingress_id=receipt.ingress_id,
        event_id=receipt.event_id,
        normalization_status=receipt.normalization_status,
        message_type=receipt.message_type,
        replay_disposition=receipt.replay_disposition,
        provider_work_order_id=receipt.provider_work_order_id,
    )


@router.post(
    "/channels/whatsapp/outbound-drafts/{draft_id}/send",
    response_model=WhatsAppCustomerReplySendResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_tenant_actions_approve)],
)
async def send_whatsapp_customer_reply(
    draft_id: str,
    payload: WhatsAppCustomerReplySendRequest,
    service: WhatsAppCustomerReplySendService = Depends(
        get_whatsapp_customer_reply_send_service
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> WhatsAppCustomerReplySendResponse:
    try:
        result = await service.send_draft(
            draft_id=draft_id,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
            recipient_phone_number=payload.recipient_phone_number,
            phone_number_id=payload.phone_number_id,
        )
    except WhatsAppCustomerReplyNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "whatsapp_reply_draft_not_found"},
        ) from exc
    except WhatsAppCustomerReplyGovernanceError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "whatsapp_reply_not_governed_send_eligible",
                "reason": str(exc),
            },
        ) from exc
    except WhatsAppCustomerReplyConfigurationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "whatsapp_channel_not_configured",
                "reason": str(exc),
            },
        ) from exc
    except WhatsAppCustomerReplyProviderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "whatsapp_provider_send_failed"},
        ) from exc
    return WhatsAppCustomerReplySendResponse(
        delivery_id=result.delivery_id,
        status=result.status,
        provider_message_id=result.provider_message_id,
        transmitted=result.transmitted,
        idempotent_replay=result.idempotent_replay,
    )


def _parse_uuid_or_404(raw: str, *, kind: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": f"{kind}_not_found"},
        ) from exc


@router.get(
    "/ingress/{ingress_id}",
    response_model=BoundaryIngressResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def get_ingress(
    ingress_id: str,
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryIngressResponse:
    iid = _parse_uuid_or_404(ingress_id, kind="ingress")
    record = await repo.get_ingress(
        BoundaryIngressId(iid),
        expected_tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "ingress_not_found"}
        )
    return BoundaryIngressResponse.from_record(record)


@router.get(
    "/egress/{egress_id}",
    response_model=BoundaryEgressResponse,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def get_egress(
    egress_id: str,
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryEgressResponse:
    eid = _parse_uuid_or_404(egress_id, kind="egress")
    record = await repo.get_egress(
        BoundaryEgressId(eid),
        expected_tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "egress_not_found"}
        )
    return BoundaryEgressResponse.from_record(record)


@router.get(
    "/ingress",
    response_model=BoundaryIngressPage,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def list_ingress(
    source_type: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryIngressPage:
    from app.boundary.enums import BoundarySourceType

    source_enum: BoundarySourceType | None = None
    if source_type is not None:
        try:
            source_enum = BoundarySourceType(source_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_source_type", "reason": str(exc)},
            ) from exc
    query = BoundaryIngressQuery(
        source_type=source_enum,
        correlation_id=correlation_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_ingress(
        query, expected_tenant_id=expected_tenant_id
    )
    return BoundaryIngressPage(
        items=[BoundaryIngressResponse.from_record(r) for r in page.ingress],
        total=page.total,
    )


@router.get(
    "/egress",
    response_model=BoundaryEgressPage,
    dependencies=[Depends(require_tenant_operations_read)],
)
async def list_egress(
    source_type: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: BoundaryPersistenceProtocol = Depends(get_boundary_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> BoundaryEgressPage:
    from app.boundary.enums import BoundarySourceType

    source_enum: BoundarySourceType | None = None
    if source_type is not None:
        try:
            source_enum = BoundarySourceType(source_type)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_source_type", "reason": str(exc)},
            ) from exc
    query = BoundaryEgressQuery(
        source_type=source_enum,
        correlation_id=correlation_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.list_egress(
        query, expected_tenant_id=expected_tenant_id
    )
    return BoundaryEgressPage(
        items=[BoundaryEgressResponse.from_record(r) for r in page.egress],
        total=page.total,
    )


__all__ = ["router"]
