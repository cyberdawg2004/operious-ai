"""Coordination read endpoints — v1 transport layer (PR-D4).

Two read endpoints over the apex ``CoordinationRecord``:

* ``GET /envelopes/{coordination_id}`` — one envelope by id.
* ``GET /envelopes``                   — paginated list filtered by
                                          (sender_id, recipient_id,
                                          message_type, status,
                                          direction, correlation_id,
                                          request_id, parent_coordination_id,
                                          runtime_instance_id).

Same constitutional posture as PR-D3: read-only, tenant scope
enforced via ``require_tenant_scope`` + ``expected_tenant_id``,
no caller-supplied tenant override, page size clamped server-side,
404 (not 403) for cross-tenant access (existence-indistinguishability).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.coordination import (
    CoordinationEnvelopeResponse,
    CoordinationEnvelopesPage,
)
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationQuery,
)
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_scope,
)
from app.dependencies.services import get_coordination_repository

router = APIRouter(tags=["coordination"])

_MIN_LIMIT = 1
_MAX_LIMIT = 100
_DEFAULT_LIMIT = 25


@router.get(
    "/envelopes/{coordination_id}",
    response_model=CoordinationEnvelopeResponse,
    dependencies=[Depends(require_tenant_operations_read)],
    summary="Get one coordination envelope",
    description=(
        "Return the apex coordination envelope identified by "
        "``coordination_id`` if it exists AND belongs to the "
        "authenticated tenant. Returns 404 for both 'not found' "
        "and 'cross-tenant' — indistinguishable on the wire."
    ),
)
async def get_envelope(
    coordination_id: str,
    repo: CoordinationPersistenceProtocol = Depends(
        get_coordination_repository
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> CoordinationEnvelopeResponse:
    record = await repo.get_envelope(
        coordination_id, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "envelope_not_found"},
        )
    return CoordinationEnvelopeResponse.from_record(record)


@router.get(
    "/envelopes",
    response_model=CoordinationEnvelopesPage,
    dependencies=[Depends(require_tenant_operations_read)],
    summary="List coordination envelopes",
    description=(
        "Paginated list of coordination envelopes for the "
        "authenticated tenant. Filters AND together. Tenant "
        "scope is forced from the request authority — caller-"
        "supplied ``tenant_id`` query parameters are not exposed."
    ),
)
async def list_envelopes(
    sender_id: str | None = Query(None),
    recipient_id: str | None = Query(None),
    message_type: str | None = Query(None),
    status: str | None = Query(None),
    direction: str | None = Query(None),
    correlation_id: str | None = Query(None),
    request_id: str | None = Query(None),
    parent_coordination_id: str | None = Query(None),
    runtime_instance_id: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    repo: CoordinationPersistenceProtocol = Depends(
        get_coordination_repository
    ),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> CoordinationEnvelopesPage:
    query = CoordinationQuery(
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_type=message_type,
        status=status,
        direction=direction,
        correlation_id=correlation_id,
        request_id=request_id,
        parent_coordination_id=parent_coordination_id,
        runtime_instance_id=runtime_instance_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.query_envelopes(
        query, expected_tenant_id=expected_tenant_id
    )
    return CoordinationEnvelopesPage(
        items=[
            CoordinationEnvelopeResponse.from_record(r)
            for r in page.items
        ],
        total=page.total,
        offset=page.offset,
    )


__all__ = ["router"]
