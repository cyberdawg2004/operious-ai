"""Queue operations endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.schemas.queue_operations import (
    DeadLetterListResponse,
    DeadLetterReplayResponse,
    QueueStatusResponse,
)
from app.dependencies.authority import (
    require_operator_authority,
    require_tenant_scope,
)
from app.dependencies.services import get_queue_operations_service
from app.identity import AuthorityContext
from app.services.queue_operations_service import (
    DeadLetterAlreadyReplayedError,
    DeadLetterCannotReplayUnknownTaskError,
    DeadLetterNotFoundError,
    QueueOperationsService,
)

router = APIRouter(tags=["operations"])


@router.get(
    "/operations/queue-status",
    response_model=QueueStatusResponse,
)
async def get_queue_status(
    expected_tenant_id: str = Depends(require_tenant_scope),
    service: QueueOperationsService = Depends(get_queue_operations_service),
) -> QueueStatusResponse:
    _ = expected_tenant_id
    return QueueStatusResponse.from_record(await service.get_queue_status())


@router.get(
    "/operations/dead-letters",
    response_model=DeadLetterListResponse,
)
async def list_dead_letters(
    queue: str | None = None,
    error_class: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    expected_tenant_id: str = Depends(require_tenant_scope),
    _authority: AuthorityContext = Depends(require_operator_authority),
    service: QueueOperationsService = Depends(get_queue_operations_service),
) -> DeadLetterListResponse:
    return DeadLetterListResponse.from_page(
        await service.list_dead_letters(
            tenant_id=expected_tenant_id,
            queue=queue,
            error_class=error_class,
            limit=limit,
            offset=offset,
        )
    )


@router.post(
    "/operations/dead-letters/{dlq_id}/replay",
    response_model=DeadLetterReplayResponse,
)
async def replay_dead_letter(
    dlq_id: str,
    expected_tenant_id: str = Depends(require_tenant_scope),
    authority: AuthorityContext = Depends(require_operator_authority),
    service: QueueOperationsService = Depends(get_queue_operations_service),
) -> DeadLetterReplayResponse:
    try:
        return DeadLetterReplayResponse.from_record(
            await service.replay_dead_letter(
                dlq_id=dlq_id,
                tenant_id=expected_tenant_id,
                replayed_by=_operator_principal(authority),
            )
        )
    except DeadLetterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "dead_letter_not_found"},
        ) from exc
    except DeadLetterAlreadyReplayedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "dead_letter_already_replayed"},
        ) from exc
    except DeadLetterCannotReplayUnknownTaskError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="cannot_replay_unknown_task",
        ) from exc


def _operator_principal(authority: AuthorityContext) -> str:
    if authority.principal_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "operator_principal_missing"},
        )
    return str(authority.principal_id)


__all__ = ["router"]
