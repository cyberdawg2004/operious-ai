"""SME approval worker tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from threading import Thread
from typing import Any, TypeVar

from app.approvals.persistence import PostgresCaseApprovalPersistence
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_session_factory
from app.db.tenant_context import set_current_tenant
from app.governance.persistence import PostgresGovernanceRepository
from app.queues import QUEUE_SME_APPROVAL
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.services.case_approval_service import CaseApprovalService
from app.sme import build_sme_review_runtime
from app.workers.celery_app import celery_app
from app.workers.queue_admission import clear_worker_queue_age

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="review_case_approval",
    queue=QUEUE_SME_APPROVAL,
    bind=True,
    ignore_result=True,
    max_retries=2,
    default_retry_delay=30,
)
def review_case_approval(
    _self: Any,
    approval_case_id: str,
    tenant_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Run SME review for one approval case."""
    del _enqueued_at

    set_current_tenant(tenant_id)
    try:
        return _run_async(
            review_case_approval_runtime(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            ),
            tenant_id=tenant_id,
        )
    finally:
        set_current_tenant(None)


async def review_case_approval_runtime(
    *,
    approval_case_id: str,
    tenant_id: str,
) -> dict[str, object]:
    set_current_tenant(tenant_id)
    try:
        await clear_worker_queue_age(
            queue_name=QUEUE_SME_APPROVAL,
            member_id=approval_case_id,
        )
        session_factory = get_session_factory()
        async with session_factory() as session:
            data_protection = _data_protection_service(session)
            service = CaseApprovalService(
                persistence=PostgresCaseApprovalPersistence(
                    session,
                    data_protection=data_protection,
                ),
                sme_runtime=build_sme_review_runtime(),
                resolution_repository=PostgresResolutionProposalPersistence(
                    session,
                    data_protection=data_protection,
                ),
                governance_repository=PostgresGovernanceRepository(session),
                session=session,
            )
            record = await service.review_case(
                approval_case_id=approval_case_id,
                tenant_id=tenant_id,
            )
            await session.commit()
            return {
                "status": "completed",
                "approval_case_id": record.approval_case_id,
                "tenant_id": record.tenant_id,
                "queue_status": record.status.value,
                "sme_recommendation_id": record.sme_recommendation_id,
            }
    finally:
        set_current_tenant(None)


def _data_protection_service(session: Any) -> DataProtectionService | None:
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


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("approval review coroutine returned no result")
    return results[0]


__all__ = ["review_case_approval", "review_case_approval_runtime"]
