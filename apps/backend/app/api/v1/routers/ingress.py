"""Ticket ingress write endpoint (PR-W1)."""

from __future__ import annotations

import json
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.v1.schemas.ingress import (
    TicketIngressRequest,
    TicketIngressResponse,
    TicketIngressWebhookResponse,
)
from app.dependencies.authority import (
    request_tenant_scope_opt,
    require_tenant_scope,
)
from app.dependencies.services import get_ticket_ingress_service
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressService,
    TicketIngressServiceError,
    WebhookDuplicateDeliveryResult,
)

router = APIRouter(tags=["ingress"])


@router.post(
    "/ingress",
    response_model=TicketIngressResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_ticket_ingress(
    request: TicketIngressRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TicketIngressService = Depends(get_ticket_ingress_service),
) -> TicketIngressResponse:
    try:
        result = await service.process(
            external_id=request.external_id,
            channel=request.channel,
            raw_content=request.raw_content,
            language_code=request.language_code,
            expected_tenant_id=expected_tenant_id,
        )
    except TicketIngressServiceError as exc:
        raise HTTPException(
            status_code=500, detail={"code": "ticket_ingress_failed"}
        ) from exc
    return TicketIngressResponse(
        ingress_id=result.ingress_id,
        canonical_envelope_id=result.canonical_envelope_id,
        quarantine_id=result.quarantine_id,
        status=result.status,
    )


@router.post(
    "/channels/{channel_type}/webhook",
    response_model=TicketIngressWebhookResponse,
)
async def create_channel_webhook_ingress(
    channel_type: str,
    request: Request,
    expected_tenant_id: str | None = Depends(request_tenant_scope_opt),
    service: TicketIngressService = Depends(get_ticket_ingress_service),
) -> TicketIngressWebhookResponse | JSONResponse:
    raw_body = await request.body()
    content_type = request.headers.get("content-type")
    try:
        body = _decode_webhook_body(
            raw_body=raw_body,
            content_type=content_type,
        )
        result = await service.process_channel_webhook(
            channel_type=channel_type,
            body=body,
            headers=dict(request.headers),
            raw_body=raw_body,
            content_type=content_type,
            tenant_hint=expected_tenant_id,
        )
    except TicketIngressRejected as exc:
        if exc.response_body is not None:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.response_body,
                headers=exc.headers,
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "reason": exc.reason},
            headers=exc.headers,
        ) from exc
    except TicketIngressServiceError as exc:
        raise HTTPException(
            status_code=500, detail={"code": "ticket_ingress_failed"}
        ) from exc
    if isinstance(result, WebhookDuplicateDeliveryResult):
        return TicketIngressWebhookResponse(
            status="duplicate_delivery_acknowledged"
        )
    return TicketIngressWebhookResponse(
        ingress_id=result.ingress_id,
        canonical_envelope_id=result.canonical_envelope_id,
    )


def _decode_webhook_body(
    *,
    raw_body: bytes,
    content_type: str | None,
) -> object:
    normalized_content_type = (content_type or "").split(";", 1)[0].strip()
    if normalized_content_type == "application/x-www-form-urlencoded":
        return {
            key: value
            for key, value in parse_qsl(raw_body.decode("utf-8"))
        }
    if not raw_body:
        return {}
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TicketIngressRejected(
            code="channel_webhook_body_malformed",
            reason="webhook body must be JSON or form encoded",
        ) from exc


__all__ = ["router"]
