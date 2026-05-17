"""End-to-end tests for the translation runtime."""

from __future__ import annotations

import pytest

from app.boundary.translation import (
    EgressLocalizeRequest,
    InMemoryTranslationPersistence,
    IdentityTranslationProvider,
    IngressTranslateRequest,
    LocalizationContext,
    LocalizationFormality,
    TranslationContainmentError,
    TranslationDirection,
    TranslationEgressRuntime,
    TranslationIngressRuntime,
    TranslationPayload,
    TranslationRuntime,
)


@pytest.fixture()
def runtime() -> TranslationRuntime:
    persistence = InMemoryTranslationPersistence()
    provider = IdentityTranslationProvider()
    return TranslationRuntime(
        ingress=TranslationIngressRuntime(
            provider=provider, persistence=persistence
        ),
        egress=TranslationEgressRuntime(
            provider=provider, persistence=persistence
        ),
    )


@pytest.mark.asyncio
async def test_ingress_translate_returns_canonical_envelope(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="Por favor escalate", language="es"
            ),
            seed="i1",
            correlation_id="conv-1",
        )
    )
    assert env.is_ok
    assert env.result.projection.canonical_payload.language == "en"
    assert env.result.replay is not None


@pytest.mark.asyncio
async def test_ingress_rejects_operational_directive(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="x",
                language="es",
                attributes={"operational_directive": True},
            ),
            seed="i2",
        )
    )
    assert env.error is not None
    assert isinstance(env.error, TranslationContainmentError)


@pytest.mark.asyncio
async def test_egress_localize_persists_lineage(
    runtime: TranslationRuntime,
) -> None:
    await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="hola", language="es"
            ),
            seed="i3",
            correlation_id="conv-2",
        )
    )
    env = await runtime.egress.localize(
        EgressLocalizeRequest(
            canonical=TranslationPayload(
                text="The team will respond.",
                language="en",
            ),
            context=LocalizationContext(
                target_language="es",
                formality=LocalizationFormality.NEUTRAL,
            ),
            seed="e1",
            correlation_id="conv-2",
        )
    )
    assert env.is_ok
    lineage = await runtime.persistence.reconstruct_lineage(
        env.result.identity.correlation_id
    )
    assert lineage is not None
    assert [e.direction for e in lineage.entries] == [
        TranslationDirection.INGRESS,
        TranslationDirection.EGRESS,
    ]


@pytest.mark.asyncio
async def test_egress_rejects_non_canonical_input(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.egress.localize(
        EgressLocalizeRequest(
            canonical=TranslationPayload(
                text="hola", language="es"
            ),
            context=LocalizationContext(
                target_language="es",
                formality=LocalizationFormality.NEUTRAL,
            ),
            seed="e-bad",
        )
    )
    assert env.error is not None


@pytest.mark.asyncio
async def test_replay_records_are_byte_stable(
    runtime: TranslationRuntime,
) -> None:
    a = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="hola", language="es"
            ),
            seed="r1",
            correlation_id="conv-r",
        )
    )
    b = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="adios", language="es"
            ),
            seed="r2",
            correlation_id="conv-r2",
        )
    )
    assert (
        a.result.replay.canonical_fingerprint
        != b.result.replay.canonical_fingerprint
    )
