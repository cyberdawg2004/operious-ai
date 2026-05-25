"""Webhook nonce cleanup worker task."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timezone
from threading import Thread
from typing import Any, TypeVar

from app.boundary.persistence import PostgresBoundaryPersistence
from app.db.session import get_owner_session_factory
from app.workers.celery_app import celery_app
from app.queues import QUEUE_WEBHOOK_MAINTENANCE

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="cleanup_expired_webhook_nonces",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=1,
    default_retry_delay=30,
)
def cleanup_expired_webhook_nonces(
    _self: Any,
    *,
    now: str | None = None,
    limit: int = 1000,
) -> dict[str, object]:
    """Delete a bounded batch of expired webhook nonce records."""

    if limit < 1:
        raise ValueError("limit must be positive")
    cutoff = _parse_datetime(now) if now is not None else datetime.now(timezone.utc)
    deleted = _run_async(
        cleanup_expired_webhook_nonces_runtime(now=cutoff, limit=limit)
    )
    return {
        "status": "completed",
        "deleted_count": deleted,
        "cutoff": cutoff.isoformat(),
    }


async def cleanup_expired_webhook_nonces_runtime(
    *,
    now: datetime,
    limit: int = 1000,
) -> int:
    if limit < 1:
        raise ValueError("limit must be positive")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        repo = PostgresBoundaryPersistence(session)
        deleted = await repo.delete_expired_webhook_nonces(
            now=now,
            limit=limit,
        )
        await session.commit()
        return deleted


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("now must be timezone-aware")
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
        raise RuntimeError("webhook nonce cleanup coroutine returned no result")
    return results[0]


__all__ = [
    "cleanup_expired_webhook_nonces",
    "cleanup_expired_webhook_nonces_runtime",
]
