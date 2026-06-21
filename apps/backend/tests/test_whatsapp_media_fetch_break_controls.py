"""B1.5 Meta WhatsApp media fetch break-controls.

Covers the pieces test_channel_webhook_adapters.py's ack-then-defer
tests don't: the two-hop fetcher's SSRF asymmetry (strict allowlist on
hop 1, open-but-IP-restricted on hop 2), the bounded-retry/dead-letter
ceiling (LOAD-BEARING — proves no retry storm), fail-soft (a
permanently-failed fetch never blocks dispatch), the dispatch-time
attachment overlay, and tenant isolation on the new table.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence import BoundaryIngressRecord, PostgresBoundaryPersistence
from app.boundary.whatsapp_media_fetch import (
    PostgresWhatsAppMediaFetchPersistence,
    WhatsAppMediaFetchStatus,
)
from app.boundary.whatsapp_media_fetcher import (
    WhatsAppGraphMediaFetcher,
    WhatsAppMediaFetchError,
)
from app.core.ssrf import SSRFValidationError
from app.runtime.db.models import DeadLetterTaskRow
from app.services.dispatch_service import DispatchService
from app.tenant.credentials import (
    build_tenant_credential_encryptor_from_settings,
)
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from app.workers.whatsapp_media_fetch_tasks import (
    fetch_whatsapp_media_runtime,
)
from app.workers.whatsapp_media_fetch_tasks import (
    _MAX_FETCH_RETRIES,  # pyright: ignore[reportPrivateUsage]
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_MASTER_KEY = "b1-5-media-fetch-master-key-32-bytes-min"

requires_s3 = pytest.mark.skipif(
    not os.environ.get("ATTACHMENTS_S3_BUCKET"),
    reason=(
        "requires ATTACHMENTS_S3_BUCKET (+ region/credentials) pointed at "
        "a real S3 bucket for the happy-path end-to-end fetch+store."
    ),
)


def _resolve_to(*addresses: str):
    def _resolver(host: str, port: int) -> list[str]:
        del host, port
        return list(addresses)

    return _resolver


async def _ensure_tenant_row(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    tenant_id: str,
) -> None:
    from sqlalchemy import text

    statement = (
        "INSERT INTO public.tenants (tenant_id, status) "
        "VALUES (:tenant_id, 'active') ON CONFLICT (tenant_id) DO NOTHING"
    )
    if pg_seed_engine is None:
        await pg_session.execute(text(statement), {"tenant_id": tenant_id})
        await pg_session.commit()
        return
    async with pg_seed_engine.begin() as connection:
        await connection.execute(text(statement), {"tenant_id": tenant_id})


def _ingress_record(
    *, tenant_id: str, ingress_id: BoundaryIngressId | None = None
) -> BoundaryIngressRecord:
    now = datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc)
    return BoundaryIngressRecord(
        ingress_id=ingress_id or BoundaryIngressId(uuid.uuid4()),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=uuid.uuid4(),
        sequence=0,
        source_type=BoundarySourceType.WHATSAPP,
        source_id="phone-number-bc",
        tenant_id=tenant_id,
        adapter_name="tenant_whatsapp_webhook_adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=None,
        event_id=None,
        original_event_id=None,
        external_message_id="wamid.bc-001",
        external_conversation_id=None,
        external_emitted_at=None,
        received_at=now,
        started_at=now,
        ended_at=now,
        latency_ms=0.5,
        correlation_id=None,
        request_id=None,
        canonical_payload={
            "channel": "whatsapp",
            "attachments": [
                {
                    "storage_status": "pending",
                    "channel": "whatsapp",
                    "provider": "meta",
                    "media_id": "media-id-bc",
                    "content_type_declared": "image/jpeg",
                }
            ],
        },
        error=None,
    )


async def _seed_whatsapp_credentials(
    *,
    pg_session: AsyncSession,
    tenant_id: str,
    routing_address: str,
    graph_api_base_url: str = "https://graph.facebook.com",
) -> None:
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(pg_session),
        credential_encryptor=build_tenant_credential_encryptor_from_settings(
            _settings()
        ),
    )
    await runtime.configure_channel(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.WHATSAPP,
        routing_address=routing_address,
        credentials={
            "access_token": "test-access-token",
            "phone_number_id": routing_address,
            "graph_api_version": "v19.0",
            "graph_api_base_url": graph_api_base_url,
        },
        webhook_secret="whatsapp-bc-secret",
        status=TenantChannelStatus.ACTIVE,
    )
    await pg_session.commit()


def _settings() -> Any:
    from app.core.config import get_settings

    return get_settings()


# ─── two-hop fetcher: SSRF asymmetry ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fetcher_resolves_and_downloads_via_injected_client() -> None:
    class _FakeResponse:
        def __init__(self, *, status_code: int, body: Any) -> None:
            self.status_code = status_code
            self._body = body
            self.content = body if isinstance(body, bytes) else b""
            self.text = "" if isinstance(body, bytes) else str(body)

        def json(self) -> Any:
            return self._body

    class _FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def get(
            self, url: str, *, headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            del timeout
            self.calls.append(url)
            assert headers["Authorization"] == "Bearer test-token"
            if "lookaside" in url:
                return _FakeResponse(status_code=200, body=b"fake-image-bytes")
            return _FakeResponse(
                status_code=200,
                body={
                    "url": "https://lookaside.fbsbx.com/signed/abc",
                    "mime_type": "image/jpeg",
                },
            )

    client = _FakeClient()
    fetcher = WhatsAppGraphMediaFetcher(
        client=client,
        ssrf_validator=_graph_validator,
    )
    resolution = await fetcher.resolve_media_url(
        "media-123",
        access_token="test-token",
        graph_api_base_url="https://graph.facebook.com",
        graph_api_version="v19.0",
    )
    assert resolution.url == "https://lookaside.fbsbx.com/signed/abc"
    assert resolution.mime_type == "image/jpeg"
    media_bytes = await fetcher.download_media(
        resolution.url, access_token="test-token"
    )
    assert media_bytes == b"fake-image-bytes"
    assert len(client.calls) == 2


def _graph_validator(
    url: str, *, allowed_hosts: Iterable[str] = ()
) -> Any:
    from app.core.ssrf import validate_public_https_url

    return validate_public_https_url(
        url,
        allowed_hosts=allowed_hosts,
        resolve=_resolve_to("93.184.216.34"),
    )


@pytest.mark.asyncio
async def test_fetcher_hop1_rejects_host_outside_strict_allowlist() -> None:
    """Hop 1's URL is built from the tenant-configured Graph API base
    URL — it gets the same strict single-host allowlist as
    WhatsAppGraphSender.send_text_message."""
    fetcher = WhatsAppGraphMediaFetcher(
        graph_allowed_hosts=("graph.facebook.com",),
        ssrf_validator=_graph_validator,
    )
    with pytest.raises(SSRFValidationError):
        await fetcher.resolve_media_url(
            "media-123",
            access_token="t",
            graph_api_base_url="https://evil.attacker.example",
            graph_api_version="v19.0",
        )


@pytest.mark.asyncio
async def test_fetcher_hop2_rejects_private_ip_even_with_open_allowlist() -> None:
    """Hop 2's host is open (Meta's dynamic CDN, not tenant-controlled)
    but still IP-class-restricted — a redirect/DNS-rebind to a private
    or link-local address must still be rejected before any bytes are
    read, never blindly trusted just because the host isn't on a
    fixed allowlist."""

    class _UnreachableClient:
        async def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
            raise AssertionError("must never reach the HTTP layer")

    fetcher = WhatsAppGraphMediaFetcher(
        client=_UnreachableClient(),
        ssrf_validator=_private_ip_validator,
    )
    with pytest.raises(SSRFValidationError):
        await fetcher.download_media(
            "https://lookaside.fbsbx.com/signed/evil", access_token="t"
        )


def _private_ip_validator(
    url: str, *, allowed_hosts: Iterable[str] = ()
) -> Any:
    from app.core.ssrf import validate_public_https_url

    return validate_public_https_url(
        url, allowed_hosts=allowed_hosts, resolve=_resolve_to("169.254.169.254")
    )


@pytest.mark.asyncio
async def test_fetcher_propagates_non_2xx_as_typed_error() -> None:
    class _ErrorResponse:
        status_code = 404
        text = "media not found"
        content = b""

        def json(self) -> Any:
            return {}

    class _ErrorClient:
        async def get(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
            return _ErrorResponse()

    fetcher = WhatsAppGraphMediaFetcher(
        client=_ErrorClient(),
        ssrf_validator=_graph_validator,
    )
    with pytest.raises(WhatsAppMediaFetchError) as exc_info:
        await fetcher.resolve_media_url(
            "media-404",
            access_token="t",
            graph_api_base_url="https://graph.facebook.com",
            graph_api_version="v19.0",
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.hop == "resolve_media_url"


# ─── bounded retry / no storm (LOAD-BEARING) + dead-letter + fail-soft ────


@pytest.mark.asyncio
async def test_bounded_retry_exhausts_then_dead_letters_without_storm(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """LOAD-BEARING: a sustained, deterministic hop-1 failure (an
    http:// — non-HTTPS — graph_api_base_url, rejected synchronously
    by the SSRF guard, no real network needed) must exhaust in exactly
    _MAX_FETCH_RETRIES + 1 attempts, dead-letter as a STATUS UPDATE
    (never a propagating exception), and never retry beyond that
    ceiling — proving no retry storm by construction."""
    tenant_id = f"bc-whatsapp-retry-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=tenant_id))
    await _seed_whatsapp_credentials(
        pg_session=pg_session,
        tenant_id=tenant_id,
        routing_address="phone-number-retry",
        graph_api_base_url="http://127.0.0.1",  # non-https -> SSRF guard rejects, no I/O
    )
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    record = await fetch_repo.create_pending(
        tenant_id=tenant_id,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.retry-001",
        media_id="media-id-retry",
        mime_type="image/jpeg",
    )
    await pg_session.commit()

    results: list[dict[str, object]] = []
    for retry_count in range(_MAX_FETCH_RETRIES + 1):
        result = await fetch_whatsapp_media_runtime(
            fetch_id=str(record.fetch_id),
            tenant_id=tenant_id,
            attempt_number=retry_count + 1,
            session=pg_session,
            retry_count=retry_count,
        )
        await pg_session.commit()
        results.append(result)

    assert [r["status"] for r in results] == (
        ["retry_requested"] * _MAX_FETCH_RETRIES + ["dead_lettered"]
    )

    resolved = await fetch_repo.get(record.fetch_id, tenant_id=tenant_id)
    assert resolved is not None
    assert resolved.status is WhatsAppMediaFetchStatus.FAILED
    assert resolved.attachment_id is None

    # One more invocation past exhaustion must be a no-op (idempotent
    # terminal state), not a fresh retry/dead-letter cycle — this is
    # what makes "bounded" actually bounded under redelivery.
    extra = await fetch_whatsapp_media_runtime(
        fetch_id=str(record.fetch_id),
        tenant_id=tenant_id,
        attempt_number=_MAX_FETCH_RETRIES + 2,
        session=pg_session,
        retry_count=_MAX_FETCH_RETRIES + 1,
    )
    assert extra["status"] == "already_resolved"

    dead_letters = (
        await pg_session.execute(
            select(DeadLetterTaskRow).where(
                DeadLetterTaskRow.tenant_id == tenant_id,
                DeadLetterTaskRow.task_name == "fetch_whatsapp_media",
            )
        )
    ).scalars().all()
    assert len(dead_letters) == 1


@pytest.mark.asyncio
async def test_fail_soft_failed_media_does_not_block_dispatch_overlay(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """A permanently-failed fetch must never appear as a blocking
    error in the coordination envelope — the placeholder resolves to
    storage_status="failed" with no attachment_id, exactly like B1b's
    rejected-attachment shape; the surrounding ticket is unaffected."""
    tenant_id = f"bc-whatsapp-failsoft-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=tenant_id))
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    record = await fetch_repo.create_pending(
        tenant_id=tenant_id,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.bc-001",
        media_id="media-id-bc",
        mime_type="image/jpeg",
    )
    await fetch_repo.mark_failed(
        record.fetch_id, tenant_id=tenant_id, error="exhausted retries"
    )
    await pg_session.commit()

    service = _bare_dispatch_service(pg_session)
    payload = await service._resolved_canonical_payload(  # pyright: ignore[reportPrivateUsage]
        ingress=ingress, tenant_id=tenant_id
    )
    attachments = payload["attachments"]
    assert isinstance(attachments, list)
    assert attachments[0]["storage_status"] == "failed"
    assert "attachment_id" not in attachments[0]


@pytest.mark.asyncio
async def test_dispatch_overlay_resolves_stored_attachment(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-whatsapp-stored-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=tenant_id))
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    record = await fetch_repo.create_pending(
        tenant_id=tenant_id,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.bc-001",
        media_id="media-id-bc",
        mime_type="image/jpeg",
    )
    resolved_attachment_id = uuid.uuid4()
    await fetch_repo.mark_stored(
        record.fetch_id, tenant_id=tenant_id, attachment_id=resolved_attachment_id
    )
    await pg_session.commit()

    service = _bare_dispatch_service(pg_session)
    payload = await service._resolved_canonical_payload(  # pyright: ignore[reportPrivateUsage]
        ingress=ingress, tenant_id=tenant_id
    )
    attachments = payload["attachments"]
    assert isinstance(attachments, list)
    assert attachments[0]["storage_status"] == "stored"
    assert attachments[0]["attachment_id"] == str(resolved_attachment_id)


@pytest.mark.asyncio
async def test_pending_media_overlay_leaves_placeholder_unchanged(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-whatsapp-pending-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=tenant_id))
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    await fetch_repo.create_pending(
        tenant_id=tenant_id,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.bc-001",
        media_id="media-id-bc",
        mime_type="image/jpeg",
    )
    await pg_session.commit()

    service = _bare_dispatch_service(pg_session)
    payload = await service._resolved_canonical_payload(  # pyright: ignore[reportPrivateUsage]
        ingress=ingress, tenant_id=tenant_id
    )
    attachments = payload["attachments"]
    assert isinstance(attachments, list)
    assert attachments[0]["storage_status"] == "pending"


# ─── tenant isolation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_cross_tenant_get_returns_none(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """Application-level defense in depth: the repository's mandatory
    tenant_id clamp on every query, mirroring AttachmentRepository's
    same guarantee. Table-level FORCE ROW LEVEL SECURITY itself is
    already covered for every tenant_id-bearing table — this one
    included, since the migration applies the identical
    _enable_tenant_rls helper — by the generic
    test_rls_coverage_invariant.py::test_every_tenant_table_forces_rls,
    which this file doesn't need to (and given pg_session's owner-role
    connection bypasses RLS by design for seeding, can't usefully) re-prove."""
    owner_tenant = f"bc-whatsapp-owner-{uuid.uuid4().hex}"
    other_tenant = f"bc-whatsapp-other-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=owner_tenant
    )
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=other_tenant
    )
    await set_pg_rls_tenant(pg_session, owner_tenant)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=owner_tenant))
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    record = await fetch_repo.create_pending(
        tenant_id=owner_tenant,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.bc-001",
        media_id="media-id-bc",
        mime_type="image/jpeg",
    )
    await pg_session.commit()

    cross_tenant_get = await fetch_repo.get(record.fetch_id, tenant_id=other_tenant)
    assert cross_tenant_get is None

    cross_tenant_list = await fetch_repo.list_by_ingress(
        uuid.UUID(str(ingress.ingress_id)), tenant_id=other_tenant
    )
    assert cross_tenant_list == ()

    same_tenant_get = await fetch_repo.get(record.fetch_id, tenant_id=owner_tenant)
    assert same_tenant_get is not None


# ─── happy path: real store() + retrievable attachment ────────────────────


@requires_s3
@pytest.mark.asyncio
async def test_happy_path_fetch_stores_and_is_retrievable(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    """End to end through the real production code path
    (fetch_whatsapp_media_runtime -> AttachmentStorageService.store()),
    with only the two Graph API HTTP hops faked (via the fetcher's
    client= test seam) — everything else (credential load, S3 upload,
    encryption, the mark_stored status transition) is real."""
    from app.attachments.identity import AttachmentId
    from app.attachments.repository import AttachmentRepository
    from app.attachments.s3_client import AttachmentBlobStore

    tenant_id = f"bc-whatsapp-happy-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    boundary = PostgresBoundaryPersistence(
        pg_session, data_protection=_data_protection(pg_session)
    )
    ingress = await boundary.save_ingress(_ingress_record(tenant_id=tenant_id))
    await _seed_whatsapp_credentials(
        pg_session=pg_session,
        tenant_id=tenant_id,
        routing_address="phone-number-happy",
    )
    fetch_repo = PostgresWhatsAppMediaFetchPersistence(pg_session)
    record = await fetch_repo.create_pending(
        tenant_id=tenant_id,
        ingress_id=uuid.UUID(str(ingress.ingress_id)),
        external_message_id="wamid.happy-001",
        media_id="media-id-happy",
        mime_type="image/jpeg",
    )
    await pg_session.commit()

    expected_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes-for-bc-test"

    class _FakeResponse:
        def __init__(self, *, body: Any) -> None:
            self.status_code = 200
            self._body = body
            self.content = body if isinstance(body, bytes) else b""
            self.text = ""

        def json(self) -> Any:
            return self._body

    class _FakeGraphClient:
        async def get(
            self, url: str, *, headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            del timeout
            assert headers["Authorization"] == "Bearer test-access-token"
            if "lookaside" in url:
                return _FakeResponse(body=expected_bytes)
            return _FakeResponse(
                body={
                    "url": "https://lookaside.fbsbx.com/signed/happy",
                    "mime_type": "image/jpeg",
                }
            )

    fetcher = WhatsAppGraphMediaFetcher(
        client=_FakeGraphClient(), ssrf_validator=_graph_validator
    )

    result = await fetch_whatsapp_media_runtime(
        fetch_id=str(record.fetch_id),
        tenant_id=tenant_id,
        session=pg_session,
        fetcher=fetcher,
    )
    await pg_session.commit()
    assert result["status"] == "success"

    resolved = await fetch_repo.get(record.fetch_id, tenant_id=tenant_id)
    assert resolved is not None
    assert resolved.status is WhatsAppMediaFetchStatus.STORED
    assert resolved.attachment_id is not None

    blob_store = AttachmentBlobStore.from_settings(_settings())
    repository = AttachmentRepository(
        pg_session, data_protection=_data_protection(pg_session), blob_store=blob_store
    )
    fetched = await repository.get(
        AttachmentId(resolved.attachment_id), tenant_id=tenant_id
    )
    assert fetched.content == expected_bytes
    assert fetched.channel == "whatsapp"
    assert fetched.external_message_id == "wamid.happy-001"

    service = _bare_dispatch_service(pg_session)
    overlaid = await service._resolved_canonical_payload(  # pyright: ignore[reportPrivateUsage]
        ingress=ingress, tenant_id=tenant_id
    )
    attachments = overlaid["attachments"]
    assert isinstance(attachments, list)
    assert attachments[0]["storage_status"] == "stored"
    assert attachments[0]["attachment_id"] == str(resolved.attachment_id)


def _data_protection(session: AsyncSession) -> Any:
    from app.data_protection.crypto import DataProtectionService

    return DataProtectionService.from_settings(session, _settings())


def _bare_dispatch_service(session: AsyncSession) -> DispatchService:
    from app.boundary.whatsapp_media_fetch import (
        PostgresWhatsAppMediaFetchPersistence as _Repo,
    )

    return DispatchService(
        coordination_runtime=None,  # type: ignore[arg-type]
        boundary_ingress_repository=None,  # type: ignore[arg-type]
        session_repository=None,  # type: ignore[arg-type]
        execution_runtime=None,  # type: ignore[arg-type]
        execution_publisher=None,  # type: ignore[arg-type]
        execution_governance_runtime=None,  # type: ignore[arg-type]
        whatsapp_media_fetch_repository=_Repo(session),
    )
