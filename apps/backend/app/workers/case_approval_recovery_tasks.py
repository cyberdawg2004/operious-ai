"""Case-approval resolution recovery worker tasks.

``approve_case``/``reject_case`` (app.services.case_approval_service) fire
the case's bound action — a real external connector call that cannot
itself be rolled back — and update the case's own row in the same
request transaction. If anything after the action resolves fails before
that transaction commits, the action's resolution durably lands while the
case's own status update never does, leaving the case stuck in
``awaiting_approval`` forever. Every other external-side-effect path in
this codebase (execution, escalation, ingress dispatch, whatsapp media
fetch, outbound send) has a ``reconcile_*`` sweep for exactly this class
of divergence; case approvals had none.

This sweep finds cases whose bound action has already resolved
(``approved``/``denied``) while the case itself is still
``awaiting_approval``, and drives the case to the matching terminal
status — reconstruction-bound to the action's own ``resolved_by``/
``resolved_at``, never to this sweep or "system".

An approved case that carries a bound resolution proposal must also be
DELIVERED — ``approve_case``'s inline path flips the proposal/draft to
send-eligible/ready in the same commit, which is the only thing that ever
lets a reply reach ``outbound.send``. A reconciled case that only drives
the case-status column is not equivalent to an inline approval: the case
looks resolved forever while its reply silently never transmits. This
sweep closes BOTH halves in one transaction via
``CaseApprovalService.complete_reconciled_resolution`` (reusing the exact
delivery path the inline approval uses, never reimplemented here) so a
reconciled approval is indistinguishable in outcome from an inline one.
Keeping the case-status update and the delivery in a single commit means
a delivery failure rolls the case-status change back too, leaving the
case ``awaiting_approval`` for the next sweep to retry both halves
together — never a case that looks "approved" with an undelivered reply.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timezone
from threading import Thread
from typing import Any, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.tools.approvals import PostgresActionApprovalRepository
from app.approvals.enums import CaseApprovalStatus
from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.boundary.outbound import PostgresOutboundSendOutboxPersistence
from app.coordination.persistence import PostgresCoordinationPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_owner_session_factory
from app.governance.persistence import PostgresGovernanceRepository
from app.queues import QUEUE_WEBHOOK_MAINTENANCE
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime import ResolutionGovernanceGate, build_resolution_governance_runtime
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.services.case_approval_service import CaseApprovalService
from app.services.outbound_auto_send_service import OutboundAutoSendService
from app.sme import build_sme_review_runtime
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

_TERMINAL_ACTION_STATUSES = ("approved", "denied")

_SELECT_STALE_CASES_SQL = text(
    """
    SELECT approval_case_id,
           tenant_id,
           recommended_action ->> 'action_approval_id' AS action_approval_id
    FROM case_approval_records
    WHERE status = 'awaiting_approval'
      AND recommended_action ->> 'action_approval_id' IS NOT NULL
    ORDER BY requested_at ASC
    LIMIT :limit
    """
)


def _data_protection_service(session: AsyncSession) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


def _build_case_approval_service(session: AsyncSession) -> CaseApprovalService:
    # resolution_governance_gate IS wired, matching get_case_approval_service
    # exactly: _deliver_resolution's revision branch fires whenever
    # metadata["sme_recommendation"]["recommended_reply"] differs from the
    # proposal's own stored reply -- which is the NORM for warranty/refund
    # cases (the SME recommendation is embedded into case metadata at
    # creation regardless of whether a human ever guides/edits it), not a
    # rare guided-case edge case. Without the gate, every such reconciled
    # delivery fails closed (confirmed live backfilling a real stuck case).
    data_protection = _data_protection_service(session)
    governance_repository = PostgresGovernanceRepository(session)
    return CaseApprovalService(
        persistence=PostgresCaseApprovalPersistence(
            session, data_protection=data_protection
        ),
        sme_runtime=build_sme_review_runtime(),
        resolution_repository=PostgresResolutionProposalPersistence(
            session, data_protection=data_protection
        ),
        governance_repository=governance_repository,
        resolution_governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=PostgresTenantConfigurationRepository(
                        session, data_protection=data_protection
                    ),
                ),
            )
        ),
        session=session,
        coordination_repository=PostgresCoordinationPersistence(
            session, data_protection=data_protection
        ),
        outbound_auto_send_service=OutboundAutoSendService(
            governance_repository=governance_repository,
            outbox_persistence=PostgresOutboundSendOutboxPersistence(session),
        ),
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator] - Celery decorators are dynamically typed; runtime wiring mirrors the other reconcile_* tasks.
    name="reconcile_stale_case_approvals",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_stale_case_approvals(
    _self: Any,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    """Drive a case to its bound action's outcome when the inline
    approve/reject path fired the action but never resolved the case."""

    return _run_async(
        reconcile_stale_case_approvals_runtime(limit=limit or 100)
    )


async def reconcile_stale_case_approvals_runtime(
    *,
    limit: int = 100,
    session: AsyncSession | None = None,
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS by design.
    # Reads only case_approval_records.recommended_action and
    # action_approval_records (both unencrypted) to detect divergence; the
    # targeted update below touches only unencrypted case columns.
    if session is not None:
        return await _reconcile(session, limit=limit)
    session_factory = get_owner_session_factory()
    async with session_factory() as owned_session:
        return await _reconcile(owned_session, limit=limit)


async def _reconcile(session: AsyncSession, *, limit: int) -> dict[str, object]:
    candidates = (
        (await session.execute(_SELECT_STALE_CASES_SQL, {"limit": limit}))
        .mappings()
        .all()
    )
    reconciled: list[dict[str, object]] = []
    skipped_pending = 0
    failed: list[dict[str, object]] = []
    action_repo = PostgresActionApprovalRepository(session)
    case_approval_service = _build_case_approval_service(session)
    for candidate in candidates:
        approval_case_id = str(candidate["approval_case_id"])
        tenant_id = str(candidate["tenant_id"])
        action_approval_id = candidate["action_approval_id"]
        try:
            outcome = await _reconcile_one(
                session,
                action_repo=action_repo,
                case_approval_service=case_approval_service,
                tenant_id=tenant_id,
                action_approval_id=str(action_approval_id),
            )
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the sweep.
            await session.rollback()
            failed.append(
                {
                    "approval_case_id": approval_case_id,
                    "error": f"{exc.__class__.__name__}: {exc}"[:240],
                }
            )
            logger.warning(
                "case_approval_reconciliation_row_failed",
                extra={"approval_case_id": approval_case_id, "tenant_id": tenant_id},
            )
            continue
        if outcome is None:
            skipped_pending += 1
            continue
        reconciled.append(outcome)
    return {
        "status": "completed",
        "candidates_scanned": len(candidates),
        "reconciled_count": len(reconciled),
        "delivered_count": sum(1 for r in reconciled if r.get("delivered")),
        "skipped_pending_count": skipped_pending,
        "failed_count": len(failed),
        "reconciled": reconciled,
        "failed": failed,
    }


async def _reconcile_one(
    session: AsyncSession,
    *,
    action_repo: PostgresActionApprovalRepository,
    case_approval_service: CaseApprovalService,
    tenant_id: str,
    action_approval_id: str,
) -> dict[str, object] | None:
    action = await action_repo.get_approval(
        action_approval_id, expected_tenant_id=tenant_id
    )
    if action is None or action.status not in _TERMINAL_ACTION_STATUSES:
        return None
    resolved_at = action.resolved_at or datetime.now(timezone.utc)
    resolved_by = action.resolved_by or "unknown"
    resolution_note = action.resolution_note or (
        f"Reconciled: bound action {action.status}, but the case's own "
        "resolution never landed inline (reconcile_stale_case_approvals)."
    )
    # Single completion path, shared with ActionApprovalService's
    # standalone Action Approvals surface (claim_and_complete_case_for_
    # action): claims the case bound to this action_approval_id (if any,
    # and still awaiting_approval) and -- if approved -- delivers its
    # resolution, same transaction, committed together below so a
    # delivery failure rolls the case-status change back too and the
    # next sweep retries both halves together.
    claimed = await case_approval_service.claim_and_complete_case_for_action(
        action_approval_id=action_approval_id,
        tenant_id=tenant_id,
        action_status=action.status,
        resolved_by=resolved_by,
        resolved_at=resolved_at,
        resolution_note=resolution_note,
    )
    if claimed is None:
        # Already resolved by the inline path or a concurrent run between
        # the detection scan and this update — not an error, just stale.
        # Nothing was written this call, so no commit/rollback is needed.
        return None
    new_status = (
        CaseApprovalStatus.APPROVED
        if action.status == "approved"
        else CaseApprovalStatus.REJECTED
    )
    await session.commit()
    logger.info(
        "case_approval_reconciled",
        extra={
            "approval_case_id": claimed.approval_case_id,
            "tenant_id": tenant_id,
            "action_approval_id": action_approval_id,
            "new_status": new_status.value,
            "delivered": claimed.delivered,
            "resolved_by": resolved_by,
        },
    )
    return {
        "approval_case_id": claimed.approval_case_id,
        "tenant_id": tenant_id,
        "action_approval_id": action_approval_id,
        "new_status": new_status.value,
        "resolved_by": resolved_by,
        "delivered": claimed.delivered,
    }


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError(
            "case approval reconciliation coroutine returned no result"
        )
    return results[0]


__all__ = [
    "reconcile_stale_case_approvals",
    "reconcile_stale_case_approvals_runtime",
]
