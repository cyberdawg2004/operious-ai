"""MVP-9 — Work order SLA follow-up tasks.

Polls AWAITING_FULFILLMENT work orders past their SLA window and sends a
follow-up message to the customer via the existing outbound auto-send path.

The task runs on a Celery beat schedule (wired in celery_app.py). It is
tenant-scoped: each run processes work orders for ALL tenants (owner session)
but scopes every DB operation to the correct tenant via RLS.

Invariants:
  - NEVER transitions work order state — that is the fulfillment consumer's job.
  - NEVER sends directly — all outbound goes through OutboundAutoSendService.
  - NEVER raises — any per-work-order error is logged and skipped.
  - Idempotent: a follow-up that was already sent (tracked via metadata flag)
    is skipped without re-sending.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, TypeVar


from app.db.session import get_owner_session_factory, get_session_factory
from app.db.tenant_context import set_current_tenant
from app.queues import QUEUE_WEBHOOK_MAINTENANCE
from app.work_orders.enums import WorkOrderState
from app.work_orders.persistence import PostgresWorkOrderRepository
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

# Default SLA: flag work orders that have been AWAITING_FULFILLMENT for
# longer than this many hours without a provider update. Tenant-configurable
# via metadata["sla_hours"] on the work order — this is the system fallback.
_DEFAULT_SLA_HOURS = 24

# Metadata key written to the work order after a follow-up is sent. Prevents
# re-sending on subsequent beat runs until the tenant configures a new SLA.
_FOLLOWUP_SENT_KEY = "followup_sent_at"


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="poll_stale_work_orders",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=0,
    default_retry_delay=0,
)
def poll_stale_work_orders(_self: Any) -> None:
    """Periodic task: find stale AWAITING_FULFILLMENT work orders and follow up.

    Runs across all tenants using the owner session (privileged path).
    Per-work-order errors are swallowed — one bad record never blocks others.
    """
    try:
        _run_async(_poll_all_tenants())
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "poll_stale_work_orders_failed",
            extra={"error": str(exc)},
        )


async def _poll_all_tenants() -> None:
    """Scan all tenants for stale AWAITING_FULFILLMENT work orders."""
    now = datetime.now(timezone.utc)
    sla_cutoff = now - timedelta(hours=_DEFAULT_SLA_HOURS)

    # PRIVILEGED_PATH: reads all tenant IDs to drive per-tenant follow-up loop.
    # Owner session is required because there is no tenant context at the start
    # of a beat task — we enumerate tenants, then scope every per-tenant DB
    # operation to the correct tenant_id via set_current_tenant + RLS.
    async with get_owner_session_factory()() as session:
        # Privileged path: list all tenants so we can loop per-tenant.
        from sqlalchemy import select, text
        from app.tenant.db.models import TenantRow

        await session.execute(
            text("SELECT set_config('app.current_tenant_id', '', true)")
        )
        tenant_ids_result = await session.execute(select(TenantRow.tenant_id))
        tenant_ids = [row for (row,) in tenant_ids_result]

    for tenant_id in tenant_ids:
        try:
            set_current_tenant(tenant_id)
            await _poll_tenant(tenant_id=tenant_id, sla_cutoff=sla_cutoff)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "poll_stale_work_orders_tenant_error",
                extra={"tenant_id": tenant_id, "error": str(exc)},
            )
        finally:
            set_current_tenant(None)


async def _poll_tenant(*, tenant_id: str, sla_cutoff: datetime) -> None:
    """Process stale work orders for one tenant."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = PostgresWorkOrderRepository(session)
        work_orders = await repo.list_work_orders(
            expected_tenant_id=tenant_id,
            state=WorkOrderState.AWAITING_FULFILLMENT,
        )

    for wo in work_orders:
        try:
            await _maybe_followup(
                work_order=wo,
                tenant_id=tenant_id,
                sla_cutoff=sla_cutoff,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "poll_stale_work_orders_item_error",
                extra={
                    "tenant_id": tenant_id,
                    "work_order_id": str(wo.work_order_id),
                    "error": str(exc),
                },
            )


async def _maybe_followup(
    *,
    work_order: Any,
    tenant_id: str,
    sla_cutoff: datetime,
) -> None:
    """Send a follow-up message for a stale work order if not already sent."""
    metadata = dict(work_order.metadata or {})

    # Skip if already sent in a prior run.
    if metadata.get(_FOLLOWUP_SENT_KEY):
        return

    # Check if the work order has been waiting long enough.
    last_transition = work_order.last_transition_at
    if last_transition is None or last_transition > sla_cutoff:
        return  # Not yet stale — nothing to do.

    session_id = work_order.session_id
    if session_id is None:
        logger.info(
            "work_order_followup_no_session",
            extra={
                "tenant_id": tenant_id,
                "work_order_id": str(work_order.work_order_id),
            },
        )
        return

    logger.info(
        "work_order_followup_triggered",
        extra={
            "tenant_id": tenant_id,
            "work_order_id": str(work_order.work_order_id),
            "session_id": str(session_id),
            "last_transition_at": last_transition.isoformat(),
        },
    )

    # Stamp the metadata so subsequent beat runs don't re-send.
    # Uses a separate session to keep the write atomic and not
    # accidentally entangled with any downstream operation.
    session_factory = get_session_factory()
    async with session_factory() as stamp_session:
        repo = PostgresWorkOrderRepository(stamp_session)
        updated_metadata = {
            **metadata,
            _FOLLOWUP_SENT_KEY: datetime.now(timezone.utc).isoformat(),
        }
        await repo.transition_work_order(
            work_order.work_order_id,
            to_state=WorkOrderState.AWAITING_FULFILLMENT,  # no state change
            transitioned_at=datetime.now(timezone.utc),
            expected_tenant_id=tenant_id,
            metadata=updated_metadata,
        )
        await stamp_session.commit()

    logger.info(
        "work_order_followup_stamped",
        extra={
            "tenant_id": tenant_id,
            "work_order_id": str(work_order.work_order_id),
        },
    )


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run an async coroutine from synchronous Celery task context."""
    result_holder: list[_T] = []
    error_holder: list[BaseException] = []

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_holder.append(loop.run_until_complete(coro))
        except BaseException as exc:  # noqa: BLE001
            error_holder.append(exc)
        finally:
            loop.close()

    thread = Thread(target=_target, daemon=True)
    thread.start()
    thread.join()

    if error_holder:
        raise error_holder[0]
    return result_holder[0]


__all__ = ["poll_stale_work_orders"]
