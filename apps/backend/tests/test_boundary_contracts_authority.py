"""Constitutional regression tests for the Wedge B2 typed-ingress
surface on every boundary request contract.

These tests pin:

1. Every ingress request contract accepts an optional
   ``authority: AuthorityContext | None`` field that defaults to
   ``None`` (the legacy path remains unchanged).
2. Constructing a contract WITHOUT ``authority`` is identical to
   pre-B2 behaviour — no caller is broken by the additive field.
3. Constructing a contract WITH ``authority`` round-trips the typed
   value object verbatim — the field is the typed authority carrier,
   not a hidden coercion target.
4. For every contract that carries BOTH the legacy ``tenant_id``
   AND the new ``authority``, the coexistence invariant fires when
   the two disagree, and is silent when they agree (or when either
   side is ``None``).
5. The two boundary core contracts (``BoundaryIngressRequest``,
   ``BoundaryEgressRequest``) do NOT carry a legacy ``tenant_id``
   field at all — they receive authority ONLY via the typed
   ``AuthorityContext``. This is the constitutional discipline for
   contracts introduced AFTER the typed-ingress doctrine: no new
   ``str | None`` tenant fields.

Anyone who weakens this surface — for example by silently dropping
the consistency check, or by making the field non-optional in a way
that breaks legacy callers, or by re-introducing parallel
``principal_id: str | None`` fields — fails this file.
"""

from __future__ import annotations

import pytest

from app.boundary.contracts.requests import (
    BoundaryEgressRequest,
    BoundaryIngressRequest,
)
from app.boundary.enums import BoundarySourceType
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.translation.contracts.requests import (
    EgressLocalizeRequest,
    IngressTranslateRequest,
)
from app.boundary.translation.enums import LocalizationFormality
from app.boundary.translation.localization.context import (
    LocalizationContext,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)
from app.boundary.voice.contracts.requests import (
    EgressSynthesizeRequest,
    IngressTranscribeRequest,
)
from app.boundary.voice.enums import AudioFormat
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.identity import AuthorityContext, TenantId


# ─── Fixtures ────────────────────────────────────────────────────────


def _ingress_payload() -> IngressPayload:
    return IngressPayload(body={"k": "v"})


def _translation_payload() -> TranslationPayload:
    return TranslationPayload(text="hello", language="es")


def _localization_context() -> LocalizationContext:
    return LocalizationContext(
        target_language="es",
        formality=LocalizationFormality.NEUTRAL,
    )


def _audio_handle() -> VoiceAudioHandle:
    return VoiceAudioHandle(
        handle="audio-1",
        audio_format=AudioFormat.WAV,
        sample_rate_hz=16000,
        duration_ms=1000,
        language="es",
    )


def _boundary_source() -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.ZENDESK,
        source_id="ep-1",
    )


# ─── BoundaryIngressRequest ──────────────────────────────────────────


def test_boundary_ingress_request_authority_defaults_to_none() -> (
    None
):
    """Legacy construction (no ``authority``) must keep working."""
    req = BoundaryIngressRequest(
        source=_boundary_source(),
        adapter_name="zendesk",
        payload=_ingress_payload(),
    )
    assert req.authority is None


def test_boundary_ingress_request_accepts_typed_authority() -> None:
    """The typed authority round-trips verbatim through the field."""
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    req = BoundaryIngressRequest(
        source=_boundary_source(),
        adapter_name="zendesk",
        payload=_ingress_payload(),
        authority=authority,
    )
    assert req.authority is authority
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_boundary_ingress_request_has_no_legacy_tenant_id_field() -> (
    None
):
    """Constitutional discipline: contracts introduced AFTER the
    typed-ingress doctrine do not carry ``str | None`` tenant fields.
    Authority is delivered ONLY through ``AuthorityContext``."""
    assert "tenant_id" not in BoundaryIngressRequest.__slots__


# ─── BoundaryEgressRequest ───────────────────────────────────────────


def test_boundary_egress_request_authority_defaults_to_none() -> None:
    req = BoundaryEgressRequest(
        source=_boundary_source(),
        adapter_name="zendesk",
        artifact={"x": 1},
    )
    assert req.authority is None


def test_boundary_egress_request_accepts_typed_authority() -> None:
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    req = BoundaryEgressRequest(
        source=_boundary_source(),
        adapter_name="zendesk",
        artifact={"x": 1},
        authority=authority,
    )
    assert req.authority is authority


def test_boundary_egress_request_has_no_legacy_tenant_id_field() -> (
    None
):
    assert "tenant_id" not in BoundaryEgressRequest.__slots__


# ─── Voice: IngressTranscribeRequest ─────────────────────────────────


def test_ingress_transcribe_authority_defaults_to_none() -> None:
    req = IngressTranscribeRequest(
        audio=_audio_handle(),
        target_language="es",
        seed="s",
    )
    assert req.authority is None
    assert req.tenant_id is None


def test_ingress_transcribe_accepts_authority_alone() -> None:
    """Typed-only callers: authority supplied, legacy field omitted."""
    authority = AuthorityContext(tenant_id=TenantId("acme"))
    req = IngressTranscribeRequest(
        audio=_audio_handle(),
        target_language="es",
        seed="s",
        authority=authority,
    )
    assert req.authority is authority
    assert req.tenant_id is None


def test_ingress_transcribe_accepts_tenant_id_alone() -> None:
    """Legacy callers: legacy field supplied, authority omitted."""
    req = IngressTranscribeRequest(
        audio=_audio_handle(),
        target_language="es",
        seed="s",
        tenant_id="acme",
    )
    assert req.tenant_id == "acme"
    assert req.authority is None


def test_ingress_transcribe_accepts_agreeing_authority_and_tenant_id() -> (
    None
):
    """Both fields supplied with matching tenant — must succeed."""
    req = IngressTranscribeRequest(
        audio=_audio_handle(),
        target_language="es",
        seed="s",
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.tenant_id == "acme"
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_ingress_transcribe_rejects_disagreeing_authority_and_tenant_id() -> (
    None
):
    """Both fields supplied with conflicting tenant — must raise."""
    with pytest.raises(
        ValueError,
        match="IngressTranscribeRequest.*authority.tenant_id.*tenant_id.*must agree",
    ):
        IngressTranscribeRequest(
            audio=_audio_handle(),
            target_language="es",
            seed="s",
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


def test_ingress_transcribe_silent_when_authority_tenant_id_is_none() -> (
    None
):
    """``authority.tenant_id=None`` is the "no tenant on the typed
    axis" channel — it must NOT conflict with a non-None legacy
    ``tenant_id``."""
    req = IngressTranscribeRequest(
        audio=_audio_handle(),
        target_language="es",
        seed="s",
        tenant_id="acme",
        authority=AuthorityContext(),
    )
    assert req.tenant_id == "acme"
    assert req.authority is not None
    assert req.authority.tenant_id is None


# ─── Voice: EgressSynthesizeRequest ──────────────────────────────────


def test_egress_synthesize_authority_defaults_to_none() -> None:
    req = EgressSynthesizeRequest(
        text="hi",
        target_language="es",
        audio_format=AudioFormat.WAV,
        sample_rate_hz=16000,
        seed="s",
    )
    assert req.authority is None
    assert req.tenant_id is None


def test_egress_synthesize_accepts_agreeing_authority_and_tenant_id() -> (
    None
):
    req = EgressSynthesizeRequest(
        text="hi",
        target_language="es",
        audio_format=AudioFormat.WAV,
        sample_rate_hz=16000,
        seed="s",
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_egress_synthesize_rejects_disagreeing_authority_and_tenant_id() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="EgressSynthesizeRequest.*authority.tenant_id.*tenant_id.*must agree",
    ):
        EgressSynthesizeRequest(
            text="hi",
            target_language="es",
            audio_format=AudioFormat.WAV,
            sample_rate_hz=16000,
            seed="s",
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


# ─── Translation: IngressTranslateRequest ────────────────────────────


def test_ingress_translate_authority_defaults_to_none() -> None:
    req = IngressTranslateRequest(
        source=_translation_payload(),
        seed="s",
    )
    assert req.authority is None
    assert req.tenant_id is None


def test_ingress_translate_accepts_agreeing_authority_and_tenant_id() -> (
    None
):
    req = IngressTranslateRequest(
        source=_translation_payload(),
        seed="s",
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_ingress_translate_rejects_disagreeing_authority_and_tenant_id() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="IngressTranslateRequest.*authority.tenant_id.*tenant_id.*must agree",
    ):
        IngressTranslateRequest(
            source=_translation_payload(),
            seed="s",
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


# ─── Translation: EgressLocalizeRequest ──────────────────────────────


def test_egress_localize_authority_defaults_to_none() -> None:
    req = EgressLocalizeRequest(
        canonical=_translation_payload(),
        context=_localization_context(),
        seed="s",
    )
    assert req.authority is None
    assert req.tenant_id is None


def test_egress_localize_accepts_agreeing_authority_and_tenant_id() -> (
    None
):
    req = EgressLocalizeRequest(
        canonical=_translation_payload(),
        context=_localization_context(),
        seed="s",
        tenant_id="acme",
        authority=AuthorityContext(tenant_id=TenantId("acme")),
    )
    assert req.authority is not None
    assert req.authority.tenant_id == "acme"


def test_egress_localize_rejects_disagreeing_authority_and_tenant_id() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="EgressLocalizeRequest.*authority.tenant_id.*tenant_id.*must agree",
    ):
        EgressLocalizeRequest(
            canonical=_translation_payload(),
            context=_localization_context(),
            seed="s",
            tenant_id="acme",
            authority=AuthorityContext(tenant_id=TenantId("beta")),
        )


# ─── Full ingress surface symmetry ───────────────────────────────────


def test_every_ingress_request_contract_carries_authority_field() -> (
    None
):
    """Constitutional symmetry: every boundary request contract MUST
    carry the typed authority field. The substrate's ingress surface
    is uniform — no contract is exempt from the typed-ingress
    doctrine."""
    contracts = (
        BoundaryIngressRequest,
        BoundaryEgressRequest,
        IngressTranscribeRequest,
        EgressSynthesizeRequest,
        IngressTranslateRequest,
        EgressLocalizeRequest,
    )
    for contract in contracts:
        assert "authority" in contract.__slots__, (
            f"{contract.__name__} must carry an `authority` slot "
            "(Wedge B2 typed-ingress invariant)"
        )
