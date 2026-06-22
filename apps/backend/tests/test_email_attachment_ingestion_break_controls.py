"""Break-control tests for PR-B1b — email attachment ingestion wiring.

Verified properties:
  BC-1  Email-with-attachment end-to-end: an SES MIME webhook carrying a
        real PDF attachment produces a tenant_attachments row
        (status=stored), the binary is encrypted in S3, and
        AttachmentRepository.get() returns the decrypted bytes matching
        the original — linked to the right message_id.
  BC-2  Tenant scoping: the stored attachment is retrievable only under
        the email's own tenant_id; a different tenant_id is refused.
  BC-3  Large-email path: an SES notification with NO inline MIME (routed
        to S3 instead) reaches MIME parsing via the now-wired
        SesRawEmailFetcher, and its attachment is stored — proving the
        previously-silently-dropped path now works.
  BC-4  S3SesRawEmailFetcher itself fetches real bytes from real S3 (the
        concrete boto3 implementation, not just the protocol).
  BC-5  Rejected attachment doesn't drop the ticket: a disallowed
        (executable-disguised-as-PDF) attachment is recorded
        status=rejected, but the email is still ingested.
  BC-6  Fail-soft: a storage-layer exception (S3 unreachable) is recorded
        as storage_status="failed" on that attachment, but the ticket
        still ingests — one attachment's failure never drops the email.
  BC-7  gcp KMS backend wiring: under DATA_PROTECTION_KMS_BACKEND=gcp, the
        REQUEST PATH (TicketIngressService._build_attachment_storage_service,
        invoked through the real process_channel_webhook entrypoint — not a
        hand-built DataProtectionService) must construct its
        DataProtectionService with the KMS unwrap callable, never omit it.
        Omitting it makes the still-wrapped ciphertext get used AS the AES
        key, which authenticates against nothing the real key wrapped —
        every attachment fails with "data key could not be authenticated"
        against the tenant's pre-existing data key. This reproduces the
        production wiring (a missing constructor kwarg) that unit tests
        built around a correctly-constructed service could never catch.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.attachments.exceptions import AttachmentNotFoundError
from app.attachments.identity import AttachmentId
from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.boundary.adapters.email_ses import (
    S3SesRawEmailFetcher,
    SesRawEmailFetcher,
    SnsMessageVerifier,
)
from app.boundary.persistence import BoundaryIngressQuery, InMemoryBoundaryPersistence
from app.core.config import Settings
from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.data_protection.db.models import DataProtectionDataKeyRow
from app.services.ticket_ingress_service import TicketIngressService
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

MASTER_KEY = "email-attachment-break-control-master-key-32b"
TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:operious-email-attach"
CERT_URL = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService.pem"
ROUTING_ADDRESS = "support@example.com"

requires_s3 = pytest.mark.skipif(
    not os.environ.get("ATTACHMENTS_S3_BUCKET"),
    reason=(
        "requires ATTACHMENTS_S3_BUCKET (+ region/credentials) pointed at "
        "a real S3 bucket to exercise the real-S3 break-controls."
    ),
)

_PDF_BYTES = b"%PDF-1.4\nfake invoice pdf body for BC-1.\n" + b"x" * 200
_EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 256


async def _ensure_tenant_row(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    tenant_id: str,
) -> None:
    statement = (
        "INSERT INTO public.tenants (tenant_id, status) "
        "VALUES (:tenant_id, 'active') ON CONFLICT (tenant_id) DO NOTHING"
    )
    if pg_seed_engine is None:
        # No separate owner engine available (already running as owner) —
        # commit (not just flush) so the row survives the deliberate
        # mid-flow rollback in TicketIngressService._process_email_sns_webhook
        # (_end_read_only_routing_transaction undoes the anonymous routing
        # lookup phase only; with join_transaction_mode="create_savepoint"
        # this commit creates a savepoint boundary that rollback can't cross).
        await pg_session.execute(text(statement), {"tenant_id": tenant_id})
        await pg_session.commit()
        return
    async with pg_seed_engine.begin() as connection:
        await connection.execute(text(statement), {"tenant_id": tenant_id})


class _FakeBlobStore:
    """In-memory blob store — used for tests that don't need real S3
    (rejected-attachment and fail-soft paths never touch S3 successfully
    anyway, or we want to simulate S3 being down)."""

    def __init__(self, *, fail_put: bool = False) -> None:
        self._objects: dict[str, bytes] = {}
        self._fail_put = fail_put

    def put(self, key: str, ciphertext: bytes) -> None:
        if self._fail_put:
            raise RuntimeError("simulated S3 outage")
        self._objects[key] = ciphertext

    def get(self, key: str) -> bytes:
        return self._objects[key]

    def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class _RecordingFetcher:
    """SesRawEmailFetcher test double that proves it was actually called,
    without needing real S3 — isolates the "does TicketIngressService wire
    the fetcher and resume parsing" question from "does boto3 talk to S3",
    which BC-4 covers separately."""

    def __init__(self, raw_email: bytes) -> None:
        self._raw_email = raw_email
        self.calls: list[tuple[str, str]] = []

    async def fetch_raw_email(
        self, *, bucket_name: str, object_key: str, tenant_id: str
    ) -> bytes:
        self.calls.append((bucket_name, object_key))
        return self._raw_email


async def _service(
    *,
    tenant_id: str,
    session: AsyncSession,
    certificate_pem: bytes,
    attachment_blob_store: AttachmentBlobStore | _FakeBlobStore | None,
    ses_raw_email_fetcher: SesRawEmailFetcher | None = None,
) -> TicketIngressService:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(platform_master_key=MASTER_KEY),
    )
    await tenant_runtime.configure_channel(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.EMAIL,
        routing_address=ROUTING_ADDRESS,
        credentials={"token": "email-token"},
        webhook_secret=TOPIC_ARN,
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=InMemoryBoundaryPersistence(),
        session=session,
        tenant_configuration_runtime=tenant_runtime,
        sns_message_verifier=SnsMessageVerifier(
            certificate_fetcher=_CertificateFetcher(certificate_pem)
        ),
        ses_raw_email_fetcher=ses_raw_email_fetcher,
        attachment_blob_store=attachment_blob_store,  # type: ignore[arg-type]
    )


class _CertificateFetcher:
    def __init__(self, certificate_pem: bytes) -> None:
        self.certificate_pem = certificate_pem

    async def fetch_certificate_pem(self, url: str) -> bytes:
        return self.certificate_pem


def _certificate() -> tuple[rsa.RSAPrivateKey, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "sns.us-east-1.amazonaws.com")]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .sign(private_key, hashes.SHA256())
    )
    return private_key, cert.public_bytes(serialization.Encoding.PEM)


def _signed_sns_body(
    *,
    private_key: rsa.RSAPrivateKey,
    message_id: str,
    timestamp: datetime,
    message: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "Type": "Notification",
        "MessageId": message_id,
        "TopicArn": TOPIC_ARN,
        "Timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "Message": message,
        "SignatureVersion": "2",
        "SigningCertURL": CERT_URL,
    }
    signature = private_key.sign(
        _canonical_sns_string(body).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    body["Signature"] = base64.b64encode(signature).decode("ascii")
    return body


def _canonical_sns_string(payload: Mapping[str, Any]) -> str:
    fields = ["Message", "MessageId", "Timestamp", "TopicArn", "Type"]
    lines: list[str] = []
    for field in fields:
        lines.append(field)
        lines.append(str(payload[field]))
    return "\n".join(lines) + "\n"


def _ses_message_inline(mime: str) -> str:
    return json.dumps(
        {
            "notificationType": "Received",
            "mail": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "messageId": "ses-message-id",
                "destination": [ROUTING_ADDRESS],
                "commonHeaders": {"to": [ROUTING_ADDRESS]},
            },
            "receipt": {"action": {"type": "SNS"}},
            "content": mime,
        },
        sort_keys=True,
    )


def _ses_message_s3_routed(*, bucket: str, key: str) -> str:
    """A SES notification with NO inline MIME — SES routed the email to S3
    instead (the large-email case). Previously SesEmailMimeError every
    time, since no fetcher was ever wired in production."""
    return json.dumps(
        {
            "notificationType": "Received",
            "mail": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "messageId": "ses-message-id-large",
                "destination": [ROUTING_ADDRESS],
                "commonHeaders": {"to": [ROUTING_ADDRESS]},
            },
            "receipt": {
                "action": {
                    "type": "S3",
                    "bucketName": bucket,
                    "objectKey": key,
                }
            },
        },
        sort_keys=True,
    )


def _mime_with_attachment(
    *, message_id: str, attachment_bytes: bytes, attachment_content_type: str
) -> str:
    encoded = base64.b64encode(attachment_bytes).decode("ascii")
    return (
        f"Message-ID: <{message_id}@example.net>\r\n"
        "Date: Mon, 08 Jun 2026 02:30:00 +0000\r\n"
        "From: Customer <customer@example.net>\r\n"
        f"To: Support <{ROUTING_ADDRESS}>\r\n"
        "Subject: Invoice attached\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=operious-boundary\r\n"
        "\r\n"
        "--operious-boundary\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Please see attached invoice.\r\n"
        "--operious-boundary\r\n"
        f"Content-Type: {attachment_content_type}; name=invoice.pdf\r\n"
        "Content-Disposition: attachment; filename=invoice.pdf\r\n"
        "Content-Transfer-Encoding: base64\r\n"
        "\r\n"
        f"{encoded}\r\n"
        "--operious-boundary--\r\n"
    )


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


# ─── BC-1 + BC-2: end-to-end stored + retrievable + tenant-scoped ─────────


@requires_s3
@pytest.mark.asyncio
async def test_email_attachment_end_to_end_stored_and_retrievable(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-email-att-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    settings = Settings()
    blob_store = AttachmentBlobStore.from_settings(settings)
    private_key, cert_pem = _certificate()

    service = await _service(
        tenant_id=tenant_id,
        session=pg_session,
        certificate_pem=cert_pem,
        attachment_blob_store=blob_store,
    )
    message_id = f"customer-bc1-{uuid.uuid4().hex}"
    mime = _mime_with_attachment(
        message_id=message_id,
        attachment_bytes=_PDF_BYTES,
        attachment_content_type="application/pdf",
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id=f"sns-{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message_inline(mime),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )
    assert result.ingress_id is not None

    # Fetch the persisted row's attachment_id via the canonical payload the
    # in-memory boundary store recorded (mirrors what B2/B3 would read).
    boundary_store = service._persistence  # type: ignore[attr-defined]
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=tenant_id,
    )
    assert page.total == 1
    record = page.ingress[0]
    attachments = record.canonical_payload["attachments"]
    assert len(attachments) == 1
    assert attachments[0]["storage_status"] == "stored"
    assert "_raw_bytes" not in attachments[0]
    attachment_id = attachments[0]["attachment_id"]
    assert record.canonical_payload["message_id"] == f"<{message_id}@example.net>"

    # Use the SAME key-derivation path as the write (DataProtectionService
    # .from_settings, reading real settings) — TicketIngressService wrote
    # via that path, not the hardcoded-test-key _dp_service() helper, so
    # verification must match or decryption fails authentication.
    repository = AttachmentRepository(
        pg_session,
        data_protection=DataProtectionService.from_settings(pg_session, settings),
        blob_store=blob_store,
    )
    fetched = await repository.get(AttachmentId(uuid.UUID(attachment_id)), tenant_id=tenant_id)
    assert fetched.content == _PDF_BYTES
    assert fetched.channel == "email"
    assert fetched.external_message_id == f"<{message_id}@example.net>"

    # BC-2: tenant scoping — a different tenant_id must never retrieve it.
    other_tenant = f"bc-email-att-wrong-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=other_tenant
    )
    with pytest.raises(AttachmentNotFoundError):
        await repository.get(
            AttachmentId(uuid.UUID(attachment_id)), tenant_id=other_tenant
        )

    blob_store.delete(fetched.storage_key)  # type: ignore[arg-type]


# ─── BC-3: large-email (SES-routed-to-S3) path now reaches parsing ────────


@pytest.mark.asyncio
async def test_large_email_routed_to_s3_now_reaches_attachment_storage(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-email-large-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    private_key, cert_pem = _certificate()
    message_id = f"customer-bc3-{uuid.uuid4().hex}"
    mime = _mime_with_attachment(
        message_id=message_id,
        attachment_bytes=_PDF_BYTES,
        attachment_content_type="application/pdf",
    )
    fetcher = _RecordingFetcher(mime.encode("utf-8"))
    fake_blob_store = _FakeBlobStore()

    service = await _service(
        tenant_id=tenant_id,
        session=pg_session,
        certificate_pem=cert_pem,
        attachment_blob_store=fake_blob_store,
        ses_raw_email_fetcher=fetcher,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id=f"sns-large-{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message_s3_routed(bucket="ses-inbound-bucket", key="emails/large-1"),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert result.ingress_id is not None, (
        "large email previously raised SesEmailMimeError unconditionally — "
        "no fetcher was ever wired in production"
    )
    assert fetcher.calls == [("ses-inbound-bucket", "emails/large-1")], (
        "TicketIngressService did not invoke the injected SesRawEmailFetcher"
    )

    boundary_store = service._persistence  # type: ignore[attr-defined]
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(), expected_tenant_id=tenant_id
    )
    attachments = page.ingress[0].canonical_payload["attachments"]
    assert attachments[0]["storage_status"] == "stored"
    assert fake_blob_store.get(
        f"{tenant_id}/{attachments[0]['attachment_id']}"
    ) is not None


# ─── BC-4: the concrete S3SesRawEmailFetcher fetches real S3 bytes ────────


@requires_s3
@pytest.mark.asyncio
async def test_s3_ses_raw_email_fetcher_retrieves_real_object() -> None:
    settings = Settings()
    # Reuses the attachments bucket/credentials available in this
    # environment to prove the fetcher's boto3 GetObject call works
    # against real S3 — LIVE_SES_* points at a different bucket in
    # production but the boto3 mechanics being verified are identical.
    fetcher = S3SesRawEmailFetcher(
        region=settings.ATTACHMENTS_S3_REGION,
        access_key_id=settings.ATTACHMENTS_S3_ACCESS_KEY_ID,
        secret_access_key=settings.ATTACHMENTS_S3_SECRET_ACCESS_KEY,
    )
    blob_store = AttachmentBlobStore.from_settings(settings)
    key = f"_verify/ses-fetch-{uuid.uuid4().hex}.eml"
    raw_email = b"Message-ID: <bc4@example.net>\r\n\r\nraw email body for BC-4\r\n"
    blob_store.put(key, raw_email)
    try:
        fetched = await fetcher.fetch_raw_email(
            bucket_name=settings.ATTACHMENTS_S3_BUCKET,
            object_key=key,
            tenant_id="bc-4-tenant",
        )
        assert fetched == raw_email
    finally:
        blob_store.delete(key)


# ─── BC-5: rejected attachment doesn't drop the ticket ────────────────────


@pytest.mark.asyncio
async def test_rejected_attachment_does_not_drop_the_ticket(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-email-reject-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    private_key, cert_pem = _certificate()
    message_id = f"customer-bc5-{uuid.uuid4().hex}"
    mime = _mime_with_attachment(
        message_id=message_id,
        attachment_bytes=_EXE_BYTES,
        attachment_content_type="application/pdf",
    )
    service = await _service(
        tenant_id=tenant_id,
        session=pg_session,
        certificate_pem=cert_pem,
        attachment_blob_store=_FakeBlobStore(),
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id=f"sns-reject-{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message_inline(mime),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert result.ingress_id is not None, (
        "a rejected attachment must never prevent the email/ticket from "
        "being ingested"
    )
    boundary_store = service._persistence  # type: ignore[attr-defined]
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(), expected_tenant_id=tenant_id
    )
    attachments = page.ingress[0].canonical_payload["attachments"]
    assert attachments[0]["storage_status"] == "rejected"
    assert "Executable" in attachments[0]["storage_rejection_reason"]


# ─── BC-6: fail-soft on a storage-layer exception ─────────────────────────


@pytest.mark.asyncio
async def test_attachment_storage_failure_is_fail_soft(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"bc-email-failsoft-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )
    private_key, cert_pem = _certificate()
    message_id = f"customer-bc6-{uuid.uuid4().hex}"
    mime = _mime_with_attachment(
        message_id=message_id,
        attachment_bytes=_PDF_BYTES,
        attachment_content_type="application/pdf",
    )
    service = await _service(
        tenant_id=tenant_id,
        session=pg_session,
        certificate_pem=cert_pem,
        attachment_blob_store=_FakeBlobStore(fail_put=True),
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id=f"sns-failsoft-{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message_inline(mime),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert result.ingress_id is not None, (
        "a storage-layer exception (S3 down) must never drop the ticket"
    )
    boundary_store = service._persistence  # type: ignore[attr-defined]
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(), expected_tenant_id=tenant_id
    )
    attachments = page.ingress[0].canonical_payload["attachments"]
    assert attachments[0]["storage_status"] == "failed"
    assert "simulated S3 outage" in attachments[0]["storage_error"]


# ─── BC-7: gcp KMS backend — request path must use the unwrap callable ────
#
# This is the regression for the master_key_unwrap-omission bug class. The
# previous tests in this file all construct DataProtectionService correctly
# via Settings() under the default (local) backend, so they could never
# have caught a missing master_key_unwrap kwarg under the gcp backend —
# that's exactly the gap that let the bug ship. This test instead drives
# the REAL production factory (_build_attachment_storage_service, reached
# only through process_channel_webhook) under a simulated gcp backend with
# a stub KMS unwrap, and proves the factory actually calls it.

_KNOWN_PLAINTEXT_KEY = b"\x42" * 32  # what "KMS" decrypts the ciphertext to
_FAKE_CIPHERTEXT_B64 = base64.b64encode(b"\x99" * 48).decode("ascii")
# Mirrors crypto.py's private _TENANT_SCOPE_ID — the stable wire-format
# scope_id every tenant-scoped data key (including production's) uses.
_TENANT_SCOPE_ID = "__tenant__"


def _stub_build_master_key_unwrap(settings: Any):
    """Stand-in for the real GCP KMS client: ignores the ciphertext bytes
    it's given and always returns the one known plaintext, so the test
    never needs real KMS credentials — it only verifies that the request
    path CALLS this callable at all, which is exactly what the bug omitted."""

    def _unwrap(_ciphertext: bytes) -> bytes:
        return _KNOWN_PLAINTEXT_KEY

    return _unwrap


@pytest.mark.asyncio
async def test_gcp_backend_attachment_path_uses_the_kms_unwrap_callable(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = f"bc-email-gcp-{uuid.uuid4().hex}"
    await _ensure_tenant_row(
        pg_seed_engine=pg_seed_engine, pg_session=pg_session, tenant_id=tenant_id
    )

    # Pre-seed the tenant-scoped data key EXACTLY as production has one
    # already: wrapped under the known plaintext "KMS would produce" —
    # mirroring anker-pilot's real, pre-existing __tenant__ row.
    ring = MasterKeyRing(keys={"v1": _KNOWN_PLAINTEXT_KEY}, active_version="v1")
    data_key_id = uuid.uuid4()
    raw_data_key = os.urandom(32)
    master_version, wrapped = ring.wrap_key(
        data_key=raw_data_key,
        tenant_id=tenant_id,
        scope="tenant",
        scope_id=_TENANT_SCOPE_ID,
        data_key_id=data_key_id,
    )
    pg_session.add(
        DataProtectionDataKeyRow(
            data_key_id=data_key_id,
            tenant_id=tenant_id,
            scope="tenant",
            scope_id=_TENANT_SCOPE_ID,
            master_key_version=master_version,
            encrypted_key=wrapped,
        )
    )
    # commit (not just flush) — TicketIngressService._process_email_sns_webhook
    # does a deliberate mid-flow rollback (_end_read_only_routing_transaction)
    # that would otherwise undo this pre-seeded row, same reason
    # _ensure_tenant_row commits instead of flushing.
    await pg_session.commit()

    gcp_settings = Settings(
        DATA_PROTECTION_KMS_BACKEND="gcp",
        DATA_PROTECTION_MASTER_KEYS=f"v1:{_FAKE_CIPHERTEXT_B64}",
        DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION="v1",
    )
    # Patch at the exact names the production module resolves at call time
    # (app.services.ticket_ingress_service's own namespace) — reproducing
    # the real call site, not a hand-built service.
    monkeypatch.setattr(
        "app.services.ticket_ingress_service.get_settings", lambda: gcp_settings
    )
    # raising=False: pre-fix, ticket_ingress_service doesn't import this
    # name at all (that's part of the bug) — the patch must still apply so
    # the test fails at the intended assertion below, not at setup.
    monkeypatch.setattr(
        "app.services.ticket_ingress_service.build_master_key_unwrap",
        _stub_build_master_key_unwrap,
        raising=False,
    )

    private_key, cert_pem = _certificate()
    message_id = f"customer-bc7-{uuid.uuid4().hex}"
    mime = _mime_with_attachment(
        message_id=message_id,
        attachment_bytes=_PDF_BYTES,
        attachment_content_type="application/pdf",
    )
    service = await _service(
        tenant_id=tenant_id,
        session=pg_session,
        certificate_pem=cert_pem,
        attachment_blob_store=_FakeBlobStore(),
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id=f"sns-bc7-{uuid.uuid4().hex}",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message_inline(mime),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )
    assert result.ingress_id is not None

    boundary_store = service._persistence  # type: ignore[attr-defined]
    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(), expected_tenant_id=tenant_id
    )
    attachments = page.ingress[0].canonical_payload["attachments"]
    # Before the fix: _build_attachment_storage_service never calls
    # build_master_key_unwrap, so it ignores this stub entirely and uses
    # the raw (fake) ciphertext as the AES key — unwrap_key on the
    # pre-seeded row (wrapped under _KNOWN_PLAINTEXT_KEY) then throws
    # InvalidTag, caught by the fail-soft except, landing here as
    # storage_status="failed" with "data key could not be authenticated".
    # After the fix: the factory calls the (stubbed) unwrap callable,
    # gets _KNOWN_PLAINTEXT_KEY back, and the pre-seeded row authenticates.
    assert attachments[0]["storage_status"] == "stored", (
        f"attachment storage did not use the KMS unwrap callable on the "
        f"request path: {attachments[0]!r}"
    )
