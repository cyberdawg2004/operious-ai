"""Spec 1a — ledger model changes: applied_by, revoked_by, revoked_at, REVOKED (#5,#22)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.tenant.change_requests import (
    TenantConfigChangeRequestRecord,
    TenantConfigChangeRequestStatus,
    TenantConfigChangeType,
)


def _record(**overrides: object) -> TenantConfigChangeRequestRecord:
    base: dict[str, object] = dict(
        change_request_id=uuid.uuid4(),
        tenant_id="00000000-0000-0000-0000-000000000001",
        change_type=TenantConfigChangeType.CHANNEL,
        proposed_payload={"channel_type": "email"},
        status=TenantConfigChangeRequestStatus.PROPOSED,
        proposed_by="p-1",
        proposed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return TenantConfigChangeRequestRecord(**base)  # type: ignore[arg-type]


def test_revoked_status_exists() -> None:
    assert TenantConfigChangeRequestStatus.REVOKED == "REVOKED"


def test_record_has_applied_by_field() -> None:
    r = _record(
        status=TenantConfigChangeRequestStatus.APPLIED,
        applied_at=datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
        applied_by="principal-applier",
    )
    assert r.applied_by == "principal-applier"


def test_record_applied_by_defaults_none() -> None:
    assert _record().applied_by is None


def test_record_has_revoked_by_field() -> None:
    r = _record(
        status=TenantConfigChangeRequestStatus.REVOKED,
        revoked_by="principal-revoker",
        revoked_at=datetime(2026, 6, 1, 13, tzinfo=timezone.utc),
    )
    assert r.revoked_by == "principal-revoker"
    assert r.revoked_at is not None


def test_record_revoked_fields_default_none() -> None:
    r = _record()
    assert r.revoked_by is None
    assert r.revoked_at is None
