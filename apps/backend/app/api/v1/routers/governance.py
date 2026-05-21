"""Governance read endpoints — v1 transport layer (Phase 3.2 / PR-D3).

Three read endpoints:

* ``GET /decisions/{decision_id}`` — one apex decision by id.
* ``GET /decisions``               — paginated decisions filterable
                                     by stage / policy_chain / subject_kind /
                                     final_decision / correlation_id /
                                     request_id.
* ``GET /traces/{decision_id}``    — the trace 1:1 with one decision.

Every handler depends on :func:`require_tenant_scope` and forwards
the resolved tenant id verbatim as ``expected_tenant_id`` to the
underlying :class:`BaseGovernanceRepository` read — that is what
materialises the row-level tenant isolation contract from PR-B2 /
``docs/governance/tenant-scoped-persistence.md`` at the HTTP
boundary.

Constitutional posture
──────────────────────
* No writes. Governance decisions are produced by substrate
  runtimes, never by HTTP callers — the wire shape here is
  audit-only.
* No direct ``Postgres*Repository`` construction (the router
  invariant in ``tests/test_router_invariants.py`` enforces this).
  The substrate's repository Protocol arrives via
  ``Depends(get_governance_repository)``.
* Caller-supplied ``tenant_id`` query parameters are forbidden —
  the tenant scope is sourced ONLY from the authenticated
  request authority. Allowing callers to widen scope would
  re-open the multi-tenant boundary that PR-B2 closed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.v1.schemas.governance import (
    GovernanceDecisionResponse,
    GovernanceDecisionsPage,
    GovernanceTraceResponse,
)
from app.dependencies.authority import require_tenant_scope
from app.dependencies.services import get_governance_repository
from app.governance.persistence import (
    BaseGovernanceRepository,
    DecisionQuery,
)

router = APIRouter(tags=["governance"])

# Sane bounds for list-endpoint pagination. Server-side enforced
# so a malicious/buggy caller cannot exhaust DB resources by
# requesting an arbitrarily large page.
_MIN_LIMIT = 1
_MAX_LIMIT = 200
_DEFAULT_LIMIT = 50


@router.get(
    "/decisions/{decision_id}",
    response_model=GovernanceDecisionResponse,
    summary="Get one governance decision",
    description=(
        "Return the apex governance decision identified by "
        "``decision_id`` if it exists AND belongs to the "
        "authenticated tenant. Returns 404 in both the "
        "''not-found'' and ''cross-tenant'' cases — the two are "
        "indistinguishable on the wire to prevent existence "
        "enumeration across tenants."
    ),
)
async def get_decision(
    decision_id: str,
    repo: BaseGovernanceRepository = Depends(get_governance_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> GovernanceDecisionResponse:
    record = await repo.get_decision(
        decision_id, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "decision_not_found"},
        )
    return GovernanceDecisionResponse.from_record(record)


@router.get(
    "/decisions",
    response_model=GovernanceDecisionsPage,
    summary="List governance decisions",
    description=(
        "Paginated list of governance decisions for the "
        "authenticated tenant. Filters AND together. Tenant "
        "scope is enforced from the request authority — caller-"
        "supplied ``tenant_id`` query parameters are forbidden."
    ),
)
async def list_decisions(
    stage: str | None = Query(None, description="Filter by enforcement stage."),
    policy_chain_id: str | None = Query(
        None, description="Filter by policy-chain identifier."
    ),
    subject_kind: str | None = Query(
        None, description="Filter by governance subject kind."
    ),
    final_decision: str | None = Query(
        None, description="Filter by final decision verdict."
    ),
    correlation_id: str | None = Query(
        None, description="Filter by correlation identifier."
    ),
    request_id: str | None = Query(
        None, description="Filter by request identifier."
    ),
    limit: int = Query(
        _DEFAULT_LIMIT, ge=_MIN_LIMIT, le=_MAX_LIMIT,
        description="Page size (clamped server-side).",
    ),
    offset: int = Query(
        0, ge=0, description="Pagination offset."
    ),
    repo: BaseGovernanceRepository = Depends(get_governance_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> GovernanceDecisionsPage:
    # Tenant scope is enforced by feeding ``expected_tenant_id``
    # into ``DecisionQuery.tenant_id``. PR-B2's Postgres backend
    # applies it as a WHERE clamp; the in-memory backend filters
    # equivalently. Note: ``query_decisions`` does not yet take a
    # separate ``expected_tenant_id`` keyword (the Protocol only
    # exposes it on point reads); funnelling through the query
    # field is the current pin until that Protocol delta lands.
    query = DecisionQuery(
        stage=stage,
        policy_chain_id=policy_chain_id,
        subject_kind=subject_kind,
        final_decision=final_decision,
        correlation_id=correlation_id,
        request_id=request_id,
        tenant_id=expected_tenant_id,
        limit=limit,
        offset=offset,
    )
    page = await repo.query_decisions(query)
    decisions = [
        GovernanceDecisionResponse.from_record(r) for r in page.items
    ]
    return GovernanceDecisionsPage(
        items=decisions,
        decisions=decisions,
        total=page.total,
        offset=page.offset,
    )


@router.get(
    "/traces/{decision_id}",
    response_model=GovernanceTraceResponse,
    summary="Get the trace for one governance decision",
    description=(
        "Return the audit trace 1:1 with the apex governance "
        "decision identified by ``decision_id``. Returns 404 "
        "(same indistinguishability contract as ``get_decision``)."
    ),
)
async def get_trace(
    decision_id: str,
    repo: BaseGovernanceRepository = Depends(get_governance_repository),
    expected_tenant_id: str = Depends(require_tenant_scope),
) -> GovernanceTraceResponse:
    record = await repo.get_trace(
        decision_id, expected_tenant_id=expected_tenant_id
    )
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "trace_not_found"},
        )
    return GovernanceTraceResponse.from_record(record)


__all__ = ["router"]
