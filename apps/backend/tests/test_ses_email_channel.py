from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from app.boundary.adapters import canonical_channel_payload_keys
from app.boundary.adapters.email_ses import (
    SnsMessageVerifier,
    validate_aws_sns_url,
)
from app.boundary.enums import BoundaryNormalizationStatus
from app.boundary.ingress_dispatch_outbox import IngressDispatchOutboxRecord
from app.boundary.persistence import (
    BoundaryIngressQuery,
    InMemoryBoundaryPersistence,
)
from app.services.ticket_ingress_service import (
    TicketIngressRejected,
    TicketIngressService,
)
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime

MASTER_KEY = "ses-email-channel-master-key-32-bytes-min"
TENANT_ID = "tenant-ses-email"
TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:operious-email"
CERT_URL = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService.pem"


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _CertificateFetcher:
    def __init__(self, certificate_pem: bytes) -> None:
        self.certificate_pem = certificate_pem
        self.urls: list[str] = []

    async def fetch_certificate_pem(self, url: str) -> bytes:
        self.urls.append(url)
        return self.certificate_pem


class _SubscriptionConfirmer:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def confirm_subscription(self, subscribe_url: str) -> None:
        self.urls.append(subscribe_url)


@pytest.mark.asyncio
async def test_ses_sns_notification_verifies_signature_and_parses_mime() -> None:
    private_key, cert_pem = _certificate()
    boundary_store = InMemoryBoundaryPersistence()
    session = _FakeSession()
    service = await _service(
        boundary_store=boundary_store,
        session=session,
        certificate_pem=cert_pem,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-message-001",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message(_mime_message()),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1
    record = page.ingress[0]
    assert result.ingress_id == str(record.ingress_id)
    assert record.normalization_status is BoundaryNormalizationStatus.OK
    assert set(record.canonical_payload) == canonical_channel_payload_keys()
    assert record.canonical_payload["channel"] == "email"
    assert record.canonical_payload["message_id"] == "<customer-001@example.net>"
    assert record.canonical_payload["conversation_id"] == "<thread-root@example.net>"
    assert record.canonical_payload["to"] == "support@example.com"
    assert record.canonical_payload["text"] == "My charger stopped working."
    assert record.canonical_payload["attachments"][0]["filename"] == "proof.txt"
    for leaked in ("Type", "TopicArn", "Message", "mail", "receipt", "content"):
        assert leaked not in record.canonical_payload
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ses_sns_notification_immediately_enqueues_committed_dispatch_outbox() -> None:
    private_key, cert_pem = _certificate()
    boundary_store = InMemoryBoundaryPersistence()
    session = _FakeSession()
    enqueued: list[IngressDispatchOutboxRecord] = []
    service = await _service(
        boundary_store=boundary_store,
        session=session,
        certificate_pem=cert_pem,
        ingress_dispatch_enqueue=enqueued.append,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-message-immediate",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message(_mime_message(message_id="customer-immediate")),
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert result.ingress_id is not None
    assert session.commits == 1
    assert len(enqueued) == 1
    assert str(enqueued[0].ingress_id) == result.ingress_id
    assert enqueued[0].tenant_id == TENANT_ID
    assert enqueued[0].channel == TenantChannelType.EMAIL.value


@pytest.mark.asyncio
async def test_ses_sns_replay_does_not_double_ingest() -> None:
    private_key, cert_pem = _certificate()
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service(
        boundary_store=boundary_store,
        session=_FakeSession(),
        certificate_pem=cert_pem,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-message-replay",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message(_mime_message(message_id="customer-replay")),
    )

    first = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )
    second = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    page = await boundary_store.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id=TENANT_ID,
    )
    assert first.ingress_id
    assert second.status == "duplicate_delivery_acknowledged"
    assert page.total == 1


@pytest.mark.asyncio
async def test_ses_sns_forged_cert_host_rejected_before_ingress() -> None:
    private_key, cert_pem = _certificate()
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service(
        boundary_store=boundary_store,
        session=_FakeSession(),
        certificate_pem=cert_pem,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-message-forged",
        timestamp=datetime.now(timezone.utc),
        message=_ses_message(_mime_message(message_id="customer-forged")),
        signing_cert_url="https://attacker.example.com/cert.pem",
    )

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers={},
            raw_body=_raw(body),
            content_type="application/json",
        )

    assert exc_info.value.code == "webhook_rejected"
    assert (
        await boundary_store.list_ingress(
            BoundaryIngressQuery(),
            expected_tenant_id=TENANT_ID,
        )
    ).total == 0


@pytest.mark.asyncio
async def test_ses_sns_stale_notification_rejected_after_verification() -> None:
    private_key, cert_pem = _certificate()
    boundary_store = InMemoryBoundaryPersistence()
    service = await _service(
        boundary_store=boundary_store,
        session=_FakeSession(),
        certificate_pem=cert_pem,
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-message-stale",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),
        message=_ses_message(_mime_message(message_id="customer-stale")),
    )

    with pytest.raises(TicketIngressRejected) as exc_info:
        await service.process_channel_webhook(
            channel_type="email",
            body=body,
            headers={},
            raw_body=_raw(body),
            content_type="application/json",
        )

    assert exc_info.value.code == "stale_webhook_timestamp"
    assert (
        await boundary_store.list_ingress(
            BoundaryIngressQuery(),
            expected_tenant_id=TENANT_ID,
        )
    ).total == 0


@pytest.mark.asyncio
async def test_ses_sns_subscription_confirmation_is_confirmed() -> None:
    private_key, cert_pem = _certificate()
    confirmer = _SubscriptionConfirmer()
    service = await _service(
        boundary_store=InMemoryBoundaryPersistence(),
        session=_FakeSession(),
        certificate_pem=cert_pem,
        subscription_confirmer=confirmer,
    )
    subscribe_url = (
        "https://sns.us-east-1.amazonaws.com/"
        "?Action=ConfirmSubscription&Token=token"
    )
    body = _signed_sns_body(
        private_key=private_key,
        message_id="sns-confirm-001",
        timestamp=datetime.now(timezone.utc),
        message="confirm",
        message_type="SubscriptionConfirmation",
        subscribe_url=subscribe_url,
        token="token",
    )

    result = await service.process_channel_webhook(
        channel_type="email",
        body=body,
        headers={},
        raw_body=_raw(body),
        content_type="application/json",
    )

    assert result.status == "subscription_confirmed"
    assert confirmer.urls == [subscribe_url]


def test_sns_url_validation_rejects_ssrf_hosts() -> None:
    validate_aws_sns_url(CERT_URL, require_pem=True)
    with pytest.raises(Exception):
        validate_aws_sns_url(
            "https://sns.us-east-1.amazonaws.com.attacker.test/cert.pem",
            require_pem=True,
        )
    with pytest.raises(Exception):
        validate_aws_sns_url("http://sns.us-east-1.amazonaws.com/cert.pem", require_pem=True)


async def _service(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    session: _FakeSession,
    certificate_pem: bytes,
    subscription_confirmer: _SubscriptionConfirmer | None = None,
    ingress_dispatch_enqueue: (
        Callable[[IngressDispatchOutboxRecord], None] | None
    ) = None,
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
        webhook_secret=TOPIC_ARN,
        status=TenantChannelStatus.ACTIVE,
    )
    return TicketIngressService(
        persistence=boundary_store,
        session=session,  # type: ignore[arg-type]
        tenant_configuration_runtime=tenant_runtime,
        sns_message_verifier=SnsMessageVerifier(
            certificate_fetcher=_CertificateFetcher(certificate_pem)
        ),
        sns_subscription_confirmer=subscription_confirmer,
        ingress_dispatch_enqueue=ingress_dispatch_enqueue,
    )


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
    return (
        private_key,
        cert.public_bytes(serialization.Encoding.PEM),
    )


def _signed_sns_body(
    *,
    private_key: rsa.RSAPrivateKey,
    message_id: str,
    timestamp: datetime,
    message: str,
    message_type: str = "Notification",
    signing_cert_url: str = CERT_URL,
    subscribe_url: str | None = None,
    token: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "Type": message_type,
        "MessageId": message_id,
        "TopicArn": TOPIC_ARN,
        "Timestamp": timestamp.isoformat().replace("+00:00", "Z"),
        "Message": message,
        "SignatureVersion": "2",
        "SigningCertURL": signing_cert_url,
    }
    if subscribe_url is not None:
        body["SubscribeURL"] = subscribe_url
    if token is not None:
        body["Token"] = token
    signature = private_key.sign(
        _canonical_sns_string(body).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    body["Signature"] = base64.b64encode(signature).decode("ascii")
    return body


def _canonical_sns_string(payload: Mapping[str, Any]) -> str:
    if payload["Type"] == "Notification":
        fields = ["Message", "MessageId", "Timestamp", "TopicArn", "Type"]
    else:
        fields = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    lines: list[str] = []
    for field in fields:
        lines.append(field)
        lines.append(str(payload[field]))
    return "\n".join(lines) + "\n"


def _ses_message(mime: str) -> str:
    return json.dumps(
        {
            "notificationType": "Received",
            "mail": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "messageId": "ses-message-id",
                "destination": ["support@example.com"],
                "commonHeaders": {"to": ["support@example.com"]},
            },
            "receipt": {"action": {"type": "SNS"}},
            "content": mime,
        },
        sort_keys=True,
    )


def _mime_message(message_id: str = "customer-001") -> str:
    return (
        f"Message-ID: <{message_id}@example.net>\r\n"
        "In-Reply-To: <thread-root@example.net>\r\n"
        "References: <thread-root@example.net>\r\n"
        "Date: Mon, 08 Jun 2026 02:30:00 +0000\r\n"
        "From: Customer <customer@example.net>\r\n"
        "To: Support <support@example.com>\r\n"
        "Subject: PowerCore support\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: multipart/mixed; boundary=operious-boundary\r\n"
        "\r\n"
        "--operious-boundary\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "My charger stopped working.\r\n"
        "--operious-boundary\r\n"
        "Content-Type: text/plain; name=proof.txt\r\n"
        "Content-Disposition: attachment; filename=proof.txt\r\n"
        "\r\n"
        "proof\r\n"
        "--operious-boundary--\r\n"
    )


def _raw(body: Mapping[str, Any]) -> bytes:
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
