"""Tenant operational observability endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.observability import (
    DeadLetterExecutionPageResponse,
    OperationalAlertPageResponse,
    OperationalMetricsResponse,
    OperationalSLODefinitionPageResponse,
    OperationalSLODefinitionRequest,
    OperationalSLODefinitionResponse,
    OperationalTraceSpanPageResponse,
    OperationalTraceSpanRequest,
    OperationalTraceSpanResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_operational_observability_service
from app.observability.enums import (
    AlertSeverity,
    AlertThresholdOperator,
    OperationalMetricName,
    OperationalTraceStatus,
)
from app.observability.identity import (
    as_operational_trace_span_id,
)
from app.services.operational_observability_service import (
    OperationalObservabilityService,
)

router = APIRouter(tags=["observability"])


@router.get("/metrics", response_model=OperationalMetricsResponse)
async def read_operational_metrics(
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalMetricsResponse:
    try:
        snapshot = await service.read_metrics(
            tenant_id=expected_tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_metrics_window"},
        ) from exc
    return OperationalMetricsResponse.from_record(snapshot)


@router.get("/dlq", response_model=DeadLetterExecutionPageResponse)
async def list_dead_letter_executions(
    execution_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> DeadLetterExecutionPageResponse:
    page = await service.list_dead_letters(
        tenant_id=expected_tenant_id,
        execution_id=execution_id,
        limit=limit,
        offset=offset,
    )
    return DeadLetterExecutionPageResponse.from_page(page)


@router.post(
    "/slo-definitions",
    response_model=OperationalSLODefinitionResponse,
)
async def define_slo(
    request: OperationalSLODefinitionRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalSLODefinitionResponse:
    try:
        record = await service.define_slo(
            tenant_id=expected_tenant_id,
            metric_name=OperationalMetricName(request.metric_name),
            threshold_operator=AlertThresholdOperator(
                request.threshold_operator
            ),
            threshold_value=request.threshold_value,
            window_minutes=request.window_minutes,
            severity=AlertSeverity(request.severity),
            enabled=request.enabled,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_slo_definition"},
        ) from exc
    return OperationalSLODefinitionResponse.from_record(record)


@router.get(
    "/slo-definitions",
    response_model=OperationalSLODefinitionPageResponse,
)
async def list_slo_definitions(
    metric_name: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalSLODefinitionPageResponse:
    try:
        metric = (
            OperationalMetricName(metric_name)
            if metric_name is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_metric_name"},
        ) from exc
    page = await service.list_slo_definitions(
        tenant_id=expected_tenant_id,
        metric_name=metric,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return OperationalSLODefinitionPageResponse.from_page(page)


@router.get(
    "/slo-definitions/{slo_id}",
    response_model=OperationalSLODefinitionResponse,
)
async def get_slo_definition(
    slo_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalSLODefinitionResponse:
    try:
        record = await service.get_slo_definition(
            tenant_id=expected_tenant_id,
            slo_id=slo_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "slo_definition_not_found"},
        ) from exc
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "slo_definition_not_found"},
        )
    return OperationalSLODefinitionResponse.from_record(record)


@router.get("/alerts", response_model=OperationalAlertPageResponse)
async def evaluate_alerts(
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalAlertPageResponse:
    try:
        page = await service.evaluate_alerts(
            tenant_id=expected_tenant_id,
            window_start=window_start,
            window_end=window_end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_alert_window"},
        ) from exc
    return OperationalAlertPageResponse.from_page(page)


@router.post("/traces", response_model=OperationalTraceSpanResponse)
async def record_trace_span(
    request: OperationalTraceSpanRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalTraceSpanResponse:
    try:
        record = await service.record_trace_span(
            tenant_id=expected_tenant_id,
            trace_id=request.trace_id,
            parent_span_id=(
                as_operational_trace_span_id(request.parent_span_id)
                if request.parent_span_id is not None
                else None
            ),
            span_name=request.span_name,
            substrate=request.substrate,
            operation=request.operation,
            started_at=request.started_at,
            ended_at=request.ended_at,
            status=OperationalTraceStatus(request.status),
            error=request.error,
            attributes=request.attributes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_trace_span"},
        ) from exc
    return OperationalTraceSpanResponse.from_record(record)


@router.get("/traces", response_model=OperationalTraceSpanPageResponse)
async def list_trace_spans(
    trace_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: OperationalObservabilityService = Depends(
        get_operational_observability_service
    ),
) -> OperationalTraceSpanPageResponse:
    page = await service.list_trace_spans(
        tenant_id=expected_tenant_id,
        trace_id=trace_id,
        limit=limit,
        offset=offset,
    )
    return OperationalTraceSpanPageResponse.from_page(page)


__all__ = ["router"]
