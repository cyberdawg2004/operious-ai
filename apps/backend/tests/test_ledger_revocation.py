"""Spec 1a — ledger service: apply() with applied_by + revoke() (#5,#22)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.tenant.change_requests import (
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeRequestPage,
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)


# ── Test doubles ─────────────────────────────────────────────────────────────


class _InMemoryRepo:
    def __init__(self) -> None:
        self._records: dict[uuid.UUID, TenantConfigChangeRequestRecord] = {}

    async def create(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._records[record.change_request_id] = record
        return record

    async def get(
        self,
        change_request_id: uuid.UUID,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord | None:
        return self._records.get(change_request_id)

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: TenantConfigChangeRequestStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantConfigChangeRequestPage:
        items = list(self._records.values())
        if status is not None:
            items = [r for r in items if r.status == status]
        return TenantConfigChangeRequestPage(
            items=tuple(items), total=len(items), limit=limit, offset=offset
        )

    async def update(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        self._records[record.change_request_id] = record
        return record


class _NullEvents:
    async def append_event(self, event: object, *, expected_tenant_id: str) -> None:
        pass


class _NullSession:
    async def commit(self) -> None:
        pass


class _NullTenantConfigService:
    async def publish_governance_policy_invalidation(
        self, *, tenant_id: str
    ) -> None:
        pass


# ── Fixtures ──────────────────────────────────────────────────────────────────


_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _approved_record() -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=uuid.uuid4(),
        tenant_id=_TENANT_ID,
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=TenantConfigChangeRequestStatus.APPROVED,
        proposed_by="p-proposer",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        approved_by="p-approver",
        approved_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc),
    )


def _record_with_status(
    status: TenantConfigChangeRequestStatus,
) -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=uuid.uuid4(),
        tenant_id=_TENANT_ID,
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=status,
        proposed_by="p-proposer",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        approved_by="p-approver" if status != TenantConfigChangeRequestStatus.PROPOSED else None,
        approved_at=datetime(2026, 6, 1, 10, tzinfo=timezone.utc) if status != TenantConfigChangeRequestStatus.PROPOSED else None,
    )


async def _service_with(
    record: TenantConfigChangeRequestRecord,
) -> TenantConfigChangeRequestService:
    repo = _InMemoryRepo()
    await repo.create(record, expected_tenant_id=record.tenant_id)
    return TenantConfigChangeRequestService(
        repository=repo,
        tenant_configuration_service=_NullTenantConfigService(),  # type: ignore[arg-type]
        event_appender=_NullEvents(),  # type: ignore[arg-type]
        session=_NullSession(),  # type: ignore[arg-type]
    )


# ── apply() tests ─────────────────────────────────────────────────────────────


async def test_apply_records_applied_by() -> None:
    record = _approved_record()
    service = await _service_with(record)
    # Patch the internal mutation so the unit test doesn't need the full
    # configuration runtime wired up.
    async def _stub_mutation(r: object) -> dict:  # noqa: ANN001
        return {"kind": "stub"}

    service._apply_config_mutation = _stub_mutation  # type: ignore[method-assign]
    result = await service.apply(
        change_request_id=record.change_request_id,
        expected_tenant_id=record.tenant_id,
        applied_by="p-who-applied",
    )
    assert result.applied_by == "p-who-applied"
    assert result.status == TenantConfigChangeRequestStatus.APPLIED


async def test_apply_without_applied_by_raises() -> None:
    record = _approved_record()
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="applied_by"):
        await service.apply(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            applied_by="",
        )


async def test_apply_revoked_raises_lifecycle_error() -> None:
    """REVOKED is a terminal state; applying it must fail."""
    record = _record_with_status(TenantConfigChangeRequestStatus.REVOKED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.apply(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            applied_by="p-applier",
        )


# ── revoke() tests ────────────────────────────────────────────────────────────


async def test_revoke_approved_becomes_revoked_with_revoker() -> None:
    record = _approved_record()
    service = await _service_with(record)
    result = await service.revoke(
        change_request_id=record.change_request_id,
        expected_tenant_id=record.tenant_id,
        revoked_by="p-revoker",
    )
    assert result.status == TenantConfigChangeRequestStatus.REVOKED
    assert result.revoked_by == "p-revoker"
    assert result.revoked_at is not None


async def test_revoke_applied_raises_lifecycle_error() -> None:
    record = _record_with_status(TenantConfigChangeRequestStatus.APPLIED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.revoke(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            revoked_by="p-revoker",
        )


async def test_revoke_proposed_raises_lifecycle_error() -> None:
    record = _record_with_status(TenantConfigChangeRequestStatus.PROPOSED)
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.revoke(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            revoked_by="p-revoker",
        )


async def test_revoke_without_revoked_by_raises() -> None:
    record = _approved_record()
    service = await _service_with(record)
    with pytest.raises(TenantConfigChangeRequestLifecycleError, match="revoked_by"):
        await service.revoke(
            change_request_id=record.change_request_id,
            expected_tenant_id=record.tenant_id,
            revoked_by="",
        )
