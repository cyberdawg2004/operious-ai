"""Voice-runtime requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.boundary.voice.enums import AudioFormat
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.identity import AuthorityContext


def _check_authority_tenant_consistency(
    *,
    contract_name: str,
    authority: AuthorityContext | None,
    tenant_id: str | None,
) -> None:
    """Enforce the Wedge B2 coexistence invariant.

    Both fields may co-exist during the typed-ingress transition.
    When BOTH carry a value, they must agree. ``None`` on either
    side is permitted — legacy callers (tenant_id only) and typed
    callers (authority only) are both supported until a later wedge
    consolidates onto the typed surface.
    """
    if (
        authority is not None
        and authority.tenant_id is not None
        and tenant_id is not None
        and authority.tenant_id != tenant_id
    ):
        raise ValueError(
            f"{contract_name}: authority.tenant_id and tenant_id "
            f"must agree when both are supplied (got "
            f"authority.tenant_id={authority.tenant_id!r}, "
            f"tenant_id={tenant_id!r})"
        )


@dataclass(frozen=True, slots=True)
class IngressTranscribeRequest:
    """Request to transcribe a customer audio stream.

    The ``authority`` field is the typed ingress surface introduced
    by Wedge B2. The legacy ``tenant_id: str | None`` is preserved
    verbatim — runtime consumers continue to read it unchanged.
    When both are supplied, the contract enforces that they agree.
    """

    audio: VoiceAudioHandle
    target_language: str
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "IngressTranscribeRequest.target_language must "
                "be non-empty"
            )
        if not self.seed:
            raise ValueError(
                "IngressTranscribeRequest.seed must be non-empty"
            )
        _check_authority_tenant_consistency(
            contract_name="IngressTranscribeRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class EgressSynthesizeRequest:
    """Request to synthesize an audio response from canonical text.

    The ``authority`` field is the typed ingress surface introduced
    by Wedge B2. The legacy ``tenant_id: str | None`` is preserved
    verbatim — runtime consumers continue to read it unchanged.
    When both are supplied, the contract enforces that they agree.
    """

    text: str
    target_language: str
    audio_format: AudioFormat
    sample_rate_hz: int
    seed: str
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    authority: AuthorityContext | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target_language:
            raise ValueError(
                "EgressSynthesizeRequest.target_language must be "
                "non-empty"
            )
        if self.sample_rate_hz <= 0:
            raise ValueError(
                "EgressSynthesizeRequest.sample_rate_hz must be > 0"
            )
        if not self.seed:
            raise ValueError(
                "EgressSynthesizeRequest.seed must be non-empty"
            )
        _check_authority_tenant_consistency(
            contract_name="EgressSynthesizeRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


__all__ = [
    "EgressSynthesizeRequest",
    "IngressTranscribeRequest",
]
