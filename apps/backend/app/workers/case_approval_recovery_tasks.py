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
``resolved_at``, never to this sweep or "system". The update only
touches unencrypted case columns (status/resolved_at/resolved_by/
resolution_note); ``metadata``/``guidance_ref`` are left untouched, so no
field-level decrypt/re-encrypt round trip is needed. It is guarded by
``WHERE status = 'awaiting_approval'`` so a second run is a no-op and a
concurrent inline resolution can never be clobbered.
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
from app.db.session import get_owner_session_factory
from app.queues import QUEUE_WEBHOOK_MAINTENANCE
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

_RECONCILE_CASE_SQL = text(
    """
    UPDATE case_approval_records
    SET status = :status,
        resolved_at = :resolved_at,
        resolved_by = :resolved_by,
        resolution_note = :resolution_note
    WHERE approval_case_id = :approval_case_id
      AND tenant_id = :tenant_id
      AND status = 'awaiting_approval'
    RETURNING approval_case_id
    """
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
    for candidate in candidates:
        approval_case_id = str(candidate["approval_case_id"])
        tenant_id = str(candidate["tenant_id"])
        action_approval_id = candidate["action_approval_id"]
        try:
            outcome = await _reconcile_one(
                session,
                action_repo=action_repo,
                approval_case_id=approval_case_id,
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
        "skipped_pending_count": skipped_pending,
        "failed_count": len(failed),
        "reconciled": reconciled,
        "failed": failed,
    }


async def _reconcile_one(
    session: AsyncSession,
    *,
    action_repo: PostgresActionApprovalRepository,
    approval_case_id: str,
    tenant_id: str,
    action_approval_id: str,
) -> dict[str, object] | None:
    action = await action_repo.get_approval(
        action_approval_id, expected_tenant_id=tenant_id
    )
    if action is None or action.status not in _TERMINAL_ACTION_STATUSES:
        return None
    new_status = (
        CaseApprovalStatus.APPROVED
        if action.status == "approved"
        else CaseApprovalStatus.REJECTED
    )
    resolved_at = action.resolved_at or datetime.now(timezone.utc)
    resolved_by = action.resolved_by or "unknown"
    resolution_note = action.resolution_note or (
        f"Reconciled: bound action {action.status}, but the case's own "
        "resolution never landed inline (reconcile_stale_case_approvals)."
    )
    row = (
        await session.execute(
            _RECONCILE_CASE_SQL,
            {
                "approval_case_id": approval_case_id,
                "tenant_id": tenant_id,
                "status": new_status.value,
                "resolved_at": resolved_at,
                "resolved_by": resolved_by,
                "resolution_note": resolution_note,
            },
        )
    ).mappings().one_or_none()
    await session.commit()
    if row is None:
        # Already resolved by the inline path or a concurrent run between
        # the detection scan and this update — not an error, just stale.
        return None
    logger.info(
        "case_approval_reconciled",
        extra={
            "approval_case_id": approval_case_id,
            "tenant_id": tenant_id,
            "action_approval_id": action_approval_id,
            "new_status": new_status.value,
            "resolved_by": resolved_by,
        },
    )
    return {
        "approval_case_id": approval_case_id,
        "tenant_id": tenant_id,
        "action_approval_id": action_approval_id,
        "new_status": new_status.value,
        "resolved_by": resolved_by,
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
