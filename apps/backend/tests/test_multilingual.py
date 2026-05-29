from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.boundary.identity import as_ingress_id
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.boundary.persistence.models import BoundaryIngressQuery
from app.boundary.translation import (
    DeterministicStubTranslationProvider,
    InMemoryTranslationPersistence,
    TranslationEgressRuntime,
    TranslationIngressRuntime,
    TranslationRuntime,
)
from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
    TranslationProviderResponse,
)
from app.boundary.translation.enums import TranslationProviderKind
from app.boundary.translation.models.payload import TranslationPayload
from app.cognition.diagnostic_runtime import DiagnosticCognitionRuntime
from app.cognition.llm import DiagnosticLLMMessage
from app.governance.capability.runtime import build_capability_governance_runtime
from app.knowledge.models import KnowledgeRetrievalResult
from app.language import LanguageDetector
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.resolution_runtime import (
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
)
from app.services.ticket_ingress_service import TicketIngressService
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime


ARABIC_TICKET = "مرحبا، أحتاج مساعدة مع شاحن أنكر لأنه لا يعمل منذ الأمس"
MASTER_KEY = "phase-2-5-f-master-key-32-bytes-minimum"


class _FakeSession:
    async def commit(self) -> None:
        return None


class _CountingProvider(DeterministicStubTranslationProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def translate(
        self, request: TranslationProviderRequest
    ) -> TranslationProviderResponse:
        self.calls += 1
        return await super().translate(request)


class _FailingProvider(BaseTranslationProvider):
    @property
    def name(self) -> str:
        return "failing"

    @property
    def kind(self) -> TranslationProviderKind:
        return TranslationProviderKind.DETERMINISTIC_STUB

    async def translate(
        self, request: TranslationProviderRequest
    ) -> TranslationProviderResponse:
        raise RuntimeError("translation provider failed")


class _FakeKnowledgeRuntime:
    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        max_tokens: int,
    ) -> KnowledgeRetrievalResult:
        _ = (top_k, max_tokens)
        return KnowledgeRetrievalResult(
            tenant_id=tenant_id,
            query=query,
            items=(),
            citations=(),
            budget_decisions=(),
            total_tokens=0,
            vector_index_name="multilingual-test",
        )


class _FakeLLMClient:
    provider_name = "provider-test"
    model_name = "model-test"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> object:
        _ = (
            system_prompt,
            messages,
            max_output_tokens,
            temperature,
            tenant_id,
        )
        raise AssertionError("snapshot test should not call the LLM")


class _UnusedUsagePersistence:
    pass


def _translation_runtime(
    provider: BaseTranslationProvider,
) -> TranslationRuntime:
    persistence = InMemoryTranslationPersistence()
    governance = build_capability_governance_runtime()
    return TranslationRuntime(
        ingress=TranslationIngressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=governance,
        ),
        egress=TranslationEgressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=governance,
        ),
    )


def test_language_detector_detects_arabic() -> None:
    detector = LanguageDetector()

    assert detector.detect(ARABIC_TICKET) == "ar"


def test_language_detector_fails_open_on_short_text() -> None:
    detector = LanguageDetector()

    assert detector.detect("hi") == "en"
    assert detector.detect("") == "en"


def test_language_detector_is_deterministic() -> None:
    detector = LanguageDetector()

    results = [detector.detect(ARABIC_TICKET) for _ in range(3)]

    assert results == ["ar", "ar", "ar"]


@pytest.mark.asyncio
async def test_ingress_translates_arabic_to_english() -> None:
    persistence = InMemoryBoundaryPersistence()
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        translation_runtime=_translation_runtime(
            DeterministicStubTranslationProvider()
        ),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "arabic-ticket")),
        channel="whatsapp",
        raw_content=ARABIC_TICKET,
        language_code="ar",
        expected_tenant_id="tenant-ar",
    )
    record = await persistence.get_ingress(
        as_ingress_id(result.ingress_id),
        expected_tenant_id="tenant-ar",
    )

    assert record is not None
    assert record.source_language == "ar"
    assert record.canonical_payload["source_language"] == "ar"
    assert str(record.canonical_payload["text"]).startswith("[ar→en]")


@pytest.mark.asyncio
async def test_whatsapp_webhook_translates_arabic_to_english() -> None:
    persistence = InMemoryBoundaryPersistence()
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
        credential_encryptor=TenantCredentialEncryptor(
            platform_master_key=MASTER_KEY,
        ),
    )
    await tenant_runtime.configure_channel(
        tenant_id="tenant-ar-webhook",
        channel_type=TenantChannelType.WHATSAPP,
        routing_address="phone-number-rt9",
        credentials={"token": "whatsapp-token"},
        webhook_secret="whatsapp-secret",
        status=TenantChannelStatus.ACTIVE,
    )
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        tenant_configuration_runtime=tenant_runtime,
        translation_runtime=_translation_runtime(
            DeterministicStubTranslationProvider()
        ),
    )
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {
                                "phone_number_id": "phone-number-rt9"
                            },
                            "messages": [
                                {
                                    "id": "wamid.rt9",
                                    "from": "15551234567",
                                    "timestamp": str(
                                        int(datetime.now(timezone.utc).timestamp())
                                    ),
                                    "type": "text",
                                    "text": {"body": ARABIC_TICKET},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    raw_body = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hmac.new(
        b"whatsapp-secret",
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    await service.process_channel_webhook(
        channel_type=TenantChannelType.WHATSAPP.value,
        body=body,
        headers={"X-Hub-Signature-256": f"sha256={digest}"},
        raw_body=raw_body,
        content_type="application/json",
    )
    page = await persistence.list_ingress(
        BoundaryIngressQuery(),
        expected_tenant_id="tenant-ar-webhook",
    )

    assert page.total == 1
    record = page.ingress[0]
    assert record.source_language == "ar"
    assert record.canonical_payload["source_language"] == "ar"
    assert str(record.canonical_payload["text"]).startswith("[ar→en]")


@pytest.mark.asyncio
async def test_ingress_english_passes_without_translation() -> None:
    persistence = InMemoryBoundaryPersistence()
    provider = _CountingProvider()
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        translation_runtime=_translation_runtime(provider),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "english-ticket")),
        channel="email",
        raw_content="My Anker charger stopped working yesterday.",
        language_code="en",
        expected_tenant_id="tenant-en",
    )
    record = await persistence.get_ingress(
        as_ingress_id(result.ingress_id),
        expected_tenant_id="tenant-en",
    )

    assert provider.calls == 0
    assert record is not None
    assert record.source_language == "en"
    assert record.canonical_payload["comment"] == (
        "My Anker charger stopped working yesterday."
    )


@pytest.mark.asyncio
async def test_translation_failure_does_not_block_ingress() -> None:
    persistence = InMemoryBoundaryPersistence()
    service = TicketIngressService(
        persistence=persistence,
        session=cast(Any, _FakeSession()),
        translation_runtime=_translation_runtime(_FailingProvider()),
    )

    result = await service.process(
        external_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "translation-fails")),
        channel="whatsapp",
        raw_content=ARABIC_TICKET,
        language_code="ar",
        expected_tenant_id="tenant-fail-open",
    )
    record = await persistence.get_ingress(
        as_ingress_id(result.ingress_id),
        expected_tenant_id="tenant-fail-open",
    )

    assert record is not None
    assert record.source_language == "en"
    assert record.canonical_payload["text"] == ARABIC_TICKET


@pytest.mark.asyncio
async def test_resolution_draft_localized_for_arabic() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(persistence=persistence).create_proposal(
        ResolutionProposalRequest(
            tenant_id="tenant-ar",
            session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "session-ar")),
            execution_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "execution-ar")),
            dispatch_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "dispatch-ar")),
            diagnostic_event_id=None,
            diagnostic_summary="Charging issue.",
            diagnostic_category="charging_issue",
            diagnostic_confidence=0.91,
            original_content="[ar→en] Charger not working.",
            source_language="ar",
        )
    )

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence,
        translation_runtime=_translation_runtime(
            DeterministicStubTranslationProvider()
        ),
    ).create_draft_for_proposal(proposal)

    assert draft.draft_body.startswith("[en→ar]")
    assert draft.metadata["source_language"] == "ar"
    assert str(draft.metadata["canonical_reply"]).startswith("Thanks")
    assert draft.metadata["localized_reply"] == draft.draft_body


@pytest.mark.asyncio
async def test_diagnostic_snapshot_includes_source_language() -> None:
    runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=cast(Any, _FakeKnowledgeRuntime()),
        llm_client=cast(Any, _FakeLLMClient()),
        usage_persistence=cast(Any, _UnusedUsagePersistence()),
    )

    snapshot = await runtime.load_reasoning_snapshot(
        tenant_id="tenant-ar",
        execution_id="execution-ar",
        dispatch_id="dispatch-ar",
        session_id="session-ar",
        content="[ar→en] Charger not working.",
        source_language="ar",
    )

    assert snapshot.source_language == "ar"
    assert "source language is: ar" in snapshot.system_prompt
    assert "respond in English" in snapshot.system_prompt
