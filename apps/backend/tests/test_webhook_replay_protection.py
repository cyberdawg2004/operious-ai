"""Phase F webhook replay protection."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.exceptions import WebhookReplayError
from app.boundary.persistence import (
    BoundaryIngressQuery,
    InMemoryBoundaryPersistence,
    PostgresBoundaryPersistence,
    WebhookNonceRecord,
)
from app.tenant.db.models import TenantRow
from app.services.ticket_ingress_service import TicketIngressService
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres

MASTER_KEY = "phase-f-replay-master-key-32-bytes-min"
TENANT_ID = "tenant-phase-f-replay"


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_webhook_with_replayed_nonce_rejected() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    session = _FakeSession()
    service = await _service_with_channel(
        boundary_store=boundary_store,
        session=session,
        webhook_secret="email-secret",
    )
    body = {
        "message_id": "email-replay-001",
        "to": "support@example.com",
        "text": "hello",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    raw_body = _raw(body)
    headers = _signed_headers(secret="email-secret", raw_body=raw_body)

    first = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )
    second = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers=headers,
        raw_body=raw_body,
        content_type="application/json",
    )

    assert first.ingress_id
    assert second.status == "duplicate_delivery_acknowledged"
    assert session.commits == 1
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_webhook_nonce_expiry_cleanup() -> None:
    store = InMemoryBoundaryPersistence()
    now = datetime.now(timezone.utc)
    expired = WebhookNonceRecord(
        tenant_id=TENANT_ID,
        channel_type="email",
        nonce="expired-message",
        received_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    live = WebhookNonceRecord(
        tenant_id=TENANT_ID,
        channel_type="email",
        nonce="live-message",
        received_at=now,
        expires_at=now + timedelta(hours=1),
    )
    await store.record_webhook_nonce(live)
    await store.record_webhook_nonce(expired)

    deleted = await store.delete_expired_webhook_nonces(now=now, limit=100)
    await store.record_webhook_nonce(expired)

    assert deleted == 1
    with pytest.raises(WebhookReplayError) as exc_info:
        await store.record_webhook_nonce(live)
    assert "already been accepted" in str(exc_info.value)


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_webhook_nonce_replay_and_cleanup(
    pg_session: AsyncSession,
) -> None:
    await pg_session.merge(TenantRow(tenant_id=TENANT_ID))
    repo = PostgresBoundaryPersistence(pg_session)
    now = datetime.now(timezone.utc)
    live = WebhookNonceRecord(
        tenant_id=TENANT_ID,
        channel_type="email",
        nonce="postgres-live-message",
        received_at=now,
        expires_at=now + timedelta(hours=1),
    )
    expired = WebhookNonceRecord(
        tenant_id=TENANT_ID,
        channel_type="email",
        nonce="postgres-expired-message",
        received_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )

    await repo.record_webhook_nonce(live)
    with pytest.raises(WebhookReplayError):
        await repo.record_webhook_nonce(live)
    await repo.record_webhook_nonce(expired)

    deleted = await repo.delete_expired_webhook_nonces(now=now, limit=10)

    assert deleted == 1


def test_webhook_nonce_migration_has_tenant_channel_nonce_uniqueness() -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0028_webhook_nonce_records.py"
    )
    source = migration_path.read_text(encoding="utf-8")

    assert "webhook_nonce_records" in source
    assert "uq_webhook_nonce_records_tenant_channel_nonce" in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source


def test_webhook_nonce_cleanup_task_is_scheduled() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    celery_source = (app_root / "workers" / "celery_app.py").read_text(
        encoding="utf-8"
    )
    task_source = (
        app_root / "workers" / "webhook_nonce_tasks.py"
    ).read_text(encoding="utf-8")

    assert '"app.workers.webhook_nonce_tasks"' in celery_source
    assert '"cleanup-expired-webhook-nonces-hourly"' in celery_source
    assert '"task": "cleanup_expired_webhook_nonces"' in celery_source
    assert '@celery_app.task(name="cleanup_expired_webhook_nonces"' in task_source


async def _service_with_channel(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    session: _FakeSession,
    webhook_secret: str,
) -> TicketIngressService:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=MASTER_KEY,
        ),
    )
    await tenant_runtime.configure_channel(
        tenant_id=TENANT_ID,
        channel_type=TenantChannelType.EMAIL,
        routing_address="support@example.com",
        credentials={"token": "email-token"},
        webhook_secret=webhook_secret,
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=boundary_store,
        session=session,  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
    )


def _signed_headers(*, secret: str, raw_body: bytes) -> dict[str, str]:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return {"X-Operious-Signature": f"sha256={digest}"}


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
