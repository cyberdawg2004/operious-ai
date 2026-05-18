"""`VoiceEgressRuntime` — text → TTS → audio handle."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from app.boundary.voice.contracts.requests import (
    EgressSynthesizeRequest,
)
from app.boundary.voice.contracts.results import (
    EgressSynthesizeResult,
)
from app.boundary.voice.enums import (
    VoiceDirection,
    VoiceStatus,
    VoiceTraceKind,
)
from app.boundary.voice.envelopes import VoiceEnvelope
from app.boundary.voice.exceptions import (
    VoiceContainmentError,
    VoiceError,
    VoiceProviderError,
    VoiceValidationError,
)
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    derive_correlation_id,
    derive_event_id,
    derive_lineage_id,
    derive_replay_id,
    derive_synthesis_id,
    derive_trace_id,
    generate_trace_id,
)
from app.boundary.voice.models.identity_bundle import (
    VoiceIdentity,
)
from app.boundary.voice.models.lineage import (
    VoiceLineageEntry,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.synthesis import (
    VoiceSynthesis,
)
from app.boundary.voice.persistence.records import (
    VoiceEgressRecord,
)
from app.boundary.voice.persistence.repository import (
    VoicePersistenceProtocol,
)
from app.boundary.voice.providers.base import (
    BaseTextToSpeechProvider,
    TextToSpeechProviderRequest,
)
from app.boundary.voice.serializers.canonical import (
    audio_handle_fingerprint,
    transcript_fingerprint,
)
from app.boundary.voice.traces.trace import VoiceTrace


class VoiceEgressRuntime:
    """Canonical-text → TTS → audio handle boundary runtime."""

    def __init__(
        self,
        *,
        provider: BaseTextToSpeechProvider,
        persistence: VoicePersistenceProtocol,
        runtime_instance_id: uuid.UUID | None = None,
    ) -> None:
        self._provider = provider
        self._persistence = persistence
        self._runtime_instance_id = (
            runtime_instance_id or uuid.uuid4()
        )
        self._sequence = 0

    @property
    def persistence(self) -> VoicePersistenceProtocol:
        return self._persistence

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    async def synthesize(
        self, request: EgressSynthesizeRequest
    ) -> VoiceEnvelope:
        kind = VoiceTraceKind.EGRESS_SYNTHESIZE
        started_at = datetime.now(UTC)
        monotonic = time.perf_counter()
        try:
            self._validate_request(request)

            response = await self._provider.synthesize(
                TextToSpeechProviderRequest(
                    text=request.text,
                    target_language=request.target_language,
                    audio_format=request.audio_format.value,
                    sample_rate_hz=request.sample_rate_hz,
                )
            )
            audio = response.audio
            if audio.language != request.target_language:
                raise VoiceProviderError(
                    f"TTS provider returned language "
                    f"{audio.language!r}; expected "
                    f"{request.target_language!r}"
                )
            text_fp = transcript_fingerprint(
                transcript=request.text,
                language=request.target_language,
            )
            audio_fp = audio_handle_fingerprint(
                handle=audio.handle,
                audio_format=audio.audio_format.value,
                sample_rate_hz=audio.sample_rate_hz,
                duration_ms=audio.duration_ms,
                language=audio.language,
            )
            ended_at = datetime.now(UTC)
            synthesis = VoiceSynthesis(
                synthesis_id=derive_synthesis_id(
                    seed=f"synthesis|{request.seed}"
                ),
                source_text=request.text,
                target_language=request.target_language,
                provider_name=response.provider_name,
                text_fingerprint=text_fp,
                audio_fingerprint=audio_fp,
                audio=audio,
                captured_at=ended_at,
            )
            identity = self._build_identity(request)
            lineage_entry = VoiceLineageEntry(
                sequence=await self._next_lineage_sequence(
                    identity.correlation_id
                ),
                direction=VoiceDirection.EGRESS,
                audio_fingerprint=audio_fp,
                transcript_fingerprint=text_fp,
                provider_name=response.provider_name,
                seed=request.seed,
            )
            replay = VoiceReplay(
                replay_id=derive_replay_id(seed=request.seed),
                seed=request.seed,
                audio_fingerprint=audio_fp,
                transcript_fingerprint=text_fp,
                provider_name=response.provider_name,
                captured_at=ended_at,
            )
            record = VoiceEgressRecord(
                identity=identity,
                synthesis=synthesis,
                lineage_entry=lineage_entry,
                replay=replay,
            )
            await self._persistence.write_egress(record)

            result = EgressSynthesizeResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                status=VoiceStatus.COMPLETED,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.attributes),
                identity=identity,
                synthesis=synthesis,
                replay=replay,
            )
            return self._envelope(
                kind,
                started_at,
                ended_at,
                monotonic,
                request,
                result,
                provider_name=response.provider_name,
                error=None,
            )
        except VoiceError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    # ── helpers ─────────────────────────────────────────────────────

    def _validate_request(
        self, request: EgressSynthesizeRequest
    ) -> None:
        if not request.text:
            raise VoiceValidationError(
                "EgressSynthesizeRequest.text must be non-empty"
            )
        if request.attributes.get("operational_directive"):
            raise VoiceContainmentError(
                "voice substrate MUST NEVER carry operational "
                "directives — caller passed "
                "'operational_directive' attribute."
            )

    def _build_identity(
        self, request: EgressSynthesizeRequest
    ) -> VoiceIdentity:
        event_id = derive_event_id(
            seed=f"egress|{request.seed}"
        )
        lineage_id = derive_lineage_id(
            seed=f"lineage|{request.correlation_id or request.seed}"
        )
        correlation_id = derive_correlation_id(
            seed=request.correlation_id or request.seed
        )
        return VoiceIdentity(
            event_id=event_id,
            lineage_id=lineage_id,
            correlation_id=correlation_id,
            seed=request.seed,
            request_id=request.request_id,
            tenant_id=request.tenant_id,
        )

    async def _next_lineage_sequence(
        self, correlation_id: VoiceCorrelationId
    ) -> int:
        existing = await self._persistence.list_lineage_entries(
            correlation_id
        )
        return existing[-1].sequence + 1 if existing else 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _envelope(
        self,
        kind: VoiceTraceKind,
        started_at: datetime,
        ended_at: datetime,
        monotonic: float,
        request: EgressSynthesizeRequest,
        result: EgressSynthesizeResult,
        *,
        provider_name: str | None,
        error: BaseException | None,
    ) -> VoiceEnvelope:
        sequence = self._sequence
        if request.correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{request.correlation_id}|"
                    f"{request.request_id}|"
                    f"{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        return VoiceEnvelope(
            trace=VoiceTrace(
                trace_id=trace_id,
                kind=kind,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                seed=request.seed,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                provider_name=provider_name,
                error=type(error).__name__ if error else None,
            ),
            result=result,
            error=error,
        )

    def _fail(
        self,
        kind: VoiceTraceKind,
        started_at: datetime,
        monotonic: float,
        request: EgressSynthesizeRequest,
        error: BaseException,
    ) -> VoiceEnvelope:
        ended_at = datetime.now(UTC)
        sequence = self._next_sequence()
        if request.correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{request.correlation_id}|"
                    f"err|{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        return VoiceEnvelope(
            trace=VoiceTrace(
                trace_id=trace_id,
                kind=kind,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                seed=request.seed,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                error=type(error).__name__,
            ),
            result=None,
            error=error,
        )


__all__ = ["VoiceEgressRuntime"]
