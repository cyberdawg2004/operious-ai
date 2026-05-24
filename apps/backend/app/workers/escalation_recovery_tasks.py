"""Escalation outbox recovery worker tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, TypeVar

from app.core.config import get_settings
from app.db.session import get_session_factory
from app.escalation.celery_publisher import CeleryEscalationPublisher
from app.escalation.persistence import PostgresEscalationPersistence
from app.escalation.runtime import EscalationAgentRuntime
from app.governance.persistence import PostgresGovernanceRepository
from app.session.persistence import PostgresSessionPersistence
from app.workers.celery_app import celery_app

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator] - Celery decorators are dynamically typed; runtime wiring mirrors execution recovery tasks.
    name="reconcile_stale_escalation_outbox",
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_stale_escalation_outbox(
    _self: Any,
    *,
    stale_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, object]:
    """Requeue and re-publish a bounded page of stale escalation outbox rows."""

    settings = get_settings()
    if lease_seconds is not None and lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else reconciled_at
        - timedelta(
            seconds=(
                lease_seconds
                if lease_seconds is not None
                else settings.ESCALATION_OUTBOX_CLAIM_LEASE_SECONDS
            )
        )
    )
    return _run_async(
        reconcile_stale_escalation_outbox_runtime(
            stale_before=threshold,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            tenant_id=tenant_id,
        )
    )


async def reconcile_stale_escalation_outbox_runtime(
    *,
    stale_before: datetime,
    limit: int = 100,
    tenant_id: str | None = None,
) -> dict[str, object]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        runtime = EscalationAgentRuntime(
            escalation_persistence=PostgresEscalationPersistence(session),
            governance_repository=PostgresGovernanceRepository(session),
            session_persistence=PostgresSessionPersistence(session),
        )
        sweep = await runtime.reconcile_stale_outbox_records(
            stale_before=stale_before,
            expected_tenant_id=tenant_id,
            limit=limit,
        )
        await session.commit()
        publisher = CeleryEscalationPublisher()
        republished: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        for outbox in sweep.requeued:
            claim = await runtime.claim_outbox_for_escalation(
                escalation_id=outbox.escalation_id,
                publisher_id="worker:escalation-recovery",
                expected_tenant_id=outbox.tenant_id,
            )
            if not claim.claimed or claim.outbox is None:
                failed.append(
                    {
                        "outbox_id": outbox.outbox_id,
                        "escalation_id": outbox.escalation_id,
                        "reason": claim.reason or "claim_refused",
                    }
                )
                continue
            await session.commit()
            try:
                await publisher.publish_governance_denial(
                    governance_decision_id=_metadata_str(
                        claim.outbox.metadata,
                        "governance_decision_id",
                    ),
                    tenant_id=claim.outbox.tenant_id,
                    session_id=_metadata_optional_str(
                        claim.outbox.metadata,
                        "session_id",
                    ),
                )
            except Exception as exc:
                await runtime.mark_outbox_failed(
                    outbox_id=claim.outbox.outbox_id,
                    claim_id=_metadata_claim_id(claim.outbox.claim_id),
                    error=_bounded_error(exc),
                    expected_tenant_id=claim.outbox.tenant_id,
                )
                await session.commit()
                failed.append(
                    {
                        "outbox_id": claim.outbox.outbox_id,
                        "escalation_id": claim.outbox.escalation_id,
                        "reason": _bounded_error(exc),
                    }
                )
                continue
            await runtime.mark_outbox_published(
                outbox_id=claim.outbox.outbox_id,
                claim_id=_metadata_claim_id(claim.outbox.claim_id),
                expected_tenant_id=claim.outbox.tenant_id,
            )
            await session.commit()
            republished.append(
                {
                    "outbox_id": claim.outbox.outbox_id,
                    "escalation_id": claim.outbox.escalation_id,
                }
            )
        return {
            "status": "completed",
            "requeued_count": len(sweep.requeued),
            "republished_count": len(republished),
            "failed_count": len(failed),
            "republished": republished,
            "failed": failed,
        }


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str:
    value = metadata.get(key)
    if value is None:
        raise ValueError(f"escalation outbox metadata missing {key}")
    return str(value)


def _metadata_optional_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None else None


def _metadata_claim_id(claim_id: str | None) -> str:
    if claim_id is None:
        raise ValueError("claimed escalation outbox missing claim_id")
    return claim_id


def _bounded_error(exc: BaseException) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    return message if len(message) <= 240 else f"{message[:237]}..."


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("stale_before must be timezone-aware")
    return parsed


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
        raise RuntimeError("escalation recovery coroutine returned no result")
    return results[0]


__all__ = [
    "reconcile_stale_escalation_outbox",
    "reconcile_stale_escalation_outbox_runtime",
]
