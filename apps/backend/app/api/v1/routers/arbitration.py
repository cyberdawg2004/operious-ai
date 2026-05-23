"""Arbitration read endpoints — v1 transport layer (PR-D5)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.arbitration import (
    ArbitrationEvaluationResponse,
    ArbitrationEvaluationsPage,
)
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationEvaluationId,
)
from app.arbitration.persistence import (
    ArbitrationPersistenceProtocol,
    ArbitrationQuery,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_arbitration_repository

router = APIRouter(tags=["arbitration"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


def _parse_uuid_or_404(raw: str, *, kind: str) -> UUID:
    """Convert a string path/query param into UUID. A malformed
    UUID is treated as 'not found' rather than 400 — the substrate
    refuses to leak whether a malformed id "would have matched"."""
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": f"{kind}_not_found"}
        ) from exc


@router.get(
    "/evaluations/{evaluation_id}",
    response_model=ArbitrationEvaluationResponse,
    summary="Get one arbitration evaluation",
)
async def get_evaluation(
    evaluation_id: str,
    repo: ArbitrationPersistenceProtocol = Depends(
        get_arbitration_repository
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> ArbitrationEvaluationResponse:
    eid = _parse_uuid_or_404(evaluation_id, kind="evaluation")
    record = await repo.get(
        ArbitrationEvaluationId(eid),
        expected_tenant_id=expected_tenant_id,
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail={"code": "evaluation_not_found"}
        )
    return ArbitrationEvaluationResponse.from_record(record)


@router.get(
    "/evaluations",
    response_model=ArbitrationEvaluationsPage,
    summary="List arbitration evaluations",
)
async def list_evaluations(
    case_id: str | None = Query(None),
    outcome: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: ArbitrationPersistenceProtocol = Depends(
        get_arbitration_repository
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> ArbitrationEvaluationsPage:
    parsed_case_id: ArbitrationCaseId | None = None
    if case_id is not None:
        parsed_case_id = ArbitrationCaseId(
            _parse_uuid_or_404(case_id, kind="evaluation")
        )
    query = ArbitrationQuery(
        case_id=parsed_case_id,
        outcome=None,  # outcome parameter intentionally not enum-validated
        correlation_id=correlation_id,
        request_id=request_id,
        limit=limit,
        offset=offset,
    )
    # The Protocol's outcome field is an Enum; we coerce string →
    # enum at this boundary so the wire accepts plain strings while
    # the substrate gets the typed enum.
    from app.arbitration.enums import ArbitrationOutcome

    if outcome is not None:
        try:
            outcome_enum = ArbitrationOutcome(outcome)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_outcome",
                    "reason": str(exc),
                },
            ) from exc
        query = ArbitrationQuery(
            case_id=parsed_case_id,
            outcome=outcome_enum,
            correlation_id=correlation_id,
            request_id=request_id,
            limit=limit,
            offset=offset,
        )
    page = await repo.list_records(
        query, expected_tenant_id=expected_tenant_id
    )
    return ArbitrationEvaluationsPage(
        items=[
            ArbitrationEvaluationResponse.from_record(r)
            for r in page.records
        ],
        total=page.total,
    )


__all__ = ["router"]
