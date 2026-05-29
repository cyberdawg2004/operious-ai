"""Trainer recommendation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.trainer import (
    TrainerRecommendationStatusPatchRequest,
    TrainingRecommendationListResponse,
    TrainingRecommendationResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_trainer_recommendation_service
from app.services.trainer_service import (
    TrainerRecommendationLifecycleError,
    TrainerRecommendationNotFoundError,
    TrainerRecommendationService,
)

router = APIRouter(tags=["trainer"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 50


@router.get(
    "/recommendations",
    response_model=TrainingRecommendationListResponse,
)
async def list_training_recommendations(
    status_filter: str = Query(
        "pending",
        alias="status",
        pattern="^(pending|acknowledged|all)$",
    ),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TrainerRecommendationService = Depends(
        get_trainer_recommendation_service
    ),
) -> TrainingRecommendationListResponse:
    page = await service.list_recommendations(
        tenant_id=expected_tenant_id,
        expected_tenant_id=expected_tenant_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TrainingRecommendationListResponse(
        items=[
            TrainingRecommendationResponse.from_record(record)
            for record in page.items
        ],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=TrainingRecommendationResponse,
)
async def update_training_recommendation_status(
    recommendation_id: str,
    request: TrainerRecommendationStatusPatchRequest,
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: TrainerRecommendationService = Depends(
        get_trainer_recommendation_service
    ),
) -> TrainingRecommendationResponse:
    try:
        record = await service.update_status(
            recommendation_id=recommendation_id,
            tenant_id=expected_tenant_id,
            expected_tenant_id=expected_tenant_id,
            status=request.status,
        )
    except TrainerRecommendationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "training_recommendation_not_found"},
        ) from exc
    except TrainerRecommendationLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "training_recommendation_status_invalid"},
        ) from exc
    return TrainingRecommendationResponse.from_record(record)


__all__ = ["router"]
