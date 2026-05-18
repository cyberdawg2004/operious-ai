"""`VoiceIngressRuntime` — audio → STT → normalised transcript."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.boundary.voice.contracts.requests import (
    IngressTranscribeRequest,
)
from app.boundary.voice.contracts.results import (
    IngressTranscribeResult,
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
)
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    derive_correlation_id,
    derive_event_id,
    derive_lineage_id,
    derive_replay_id,
    derive_trace_id,
    derive_transcript_id,
    generate_trace_id,
)
from app.boundary.voice.models.identity_bundle import (
    VoiceIdentity,
)
from app.boundary.voice.models.lineage import (
    VoiceLineageEntry,
)
from app.boundary.voice.models.replay import VoiceReplay
from app.boundary.voice.models.transcript import (
    VoiceTranscript,
)
from app.boundary.voice.normalization.normalizer import (
    VoiceNormalizer,
)
from app.boundary.voice.persistence.records import (
    VoiceIngressRecord,
)
from app.boundary.voice.persistence.repository import (
    VoicePersistenceProtocol,
)
from app.boundary.voice.providers.base import (
    BaseSpeechToTextProvider,
    SpeechToTextProviderRequest,
)
from app.boundary.voice.serializers.canonical import (
    audio_handle_fingerprint,
    transcript_fingerprint,
)
from app.boundary.voice.traces.trace import VoiceTrace


class VoiceIngressRuntime:
    """Audio → STT → normalised transcript boundary runtime."""

    def __init__(
        self,
        *,
        provider: BaseSpeechToTextProvider,
        persistence: VoicePersistenceProtocol,
        normalizer: VoiceNormalizer | None = None,
        runtime_instance_id: uuid.UUID | None = None,
    ) -> None:
        self._provider = provider
        self._persistence = persistence
        self._normalizer = normalizer or VoiceNormalizer()
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

    async def transcribe(
        self, request: IngressTranscribeRequest
    ) -> VoiceEnvelope:
        kind = VoiceTraceKind.INGRESS_TRANSCRIBE
        started_at = datetime.now(UTC)
        monotonic = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        try:
            self._validate_request(request)

            response = await self._provider.transcribe(
                SpeechToTextProviderRequest(
                    audio=request.audio,
                    target_language=request.target_language,
                )
            )
            if response.language != request.target_language:
                raise VoiceProviderError(
                    f"STT provider returned language "
                    f"{response.language!r}; expected "
                    f"{request.target_language!r}"
                )
            normalised = self._normalizer.normalize(
                response.transcript
            )

            audio_fp = audio_handle_fingerprint(
                handle=request.audio.handle,
                audio_format=request.audio.audio_format.value,
                sample_rate_hz=request.audio.sample_rate_hz,
                duration_ms=request.audio.duration_ms,
                language=request.audio.language,
            )
            transcript_fp = transcript_fingerprint(
                transcript=normalised,
                language=request.target_language,
            )
            ended_at = datetime.now(UTC)

            transcript = VoiceTranscript(
                transcript_id=derive_transcript_id(
                    seed=f"transcript|{request.seed}"
                ),
                text=normalised,
                language=request.target_language,
                confidence=response.confidence,
                provider_name=response.provider_name,
                audio_fingerprint=audio_fp,
                transcript_fingerprint=transcript_fp,
                audio=request.audio,
                captured_at=ended_at,
            )
            identity = self._build_identity(request, resolution=resolution)
            lineage_entry = VoiceLineageEntry(
                sequence=await self._next_lineage_sequence(
                    identity.correlation_id
                ),
                direction=VoiceDirection.INGRESS,
                audio_fingerprint=audio_fp,
                transcript_fingerprint=transcript_fp,
                provider_name=response.provider_name,
                seed=request.seed,
            )
            replay = VoiceReplay(
                replay_id=derive_replay_id(seed=request.seed),
                seed=request.seed,
                audio_fingerprint=audio_fp,
                transcript_fingerprint=transcript_fp,
                provider_name=response.provider_name,
                captured_at=ended_at,
            )

            record = VoiceIngressRecord(
                identity=identity,
                transcript=transcript,
                lineage_entry=lineage_entry,
                replay=replay,
            )
            await self._persistence.write_ingress(record)

            result = IngressTranscribeResult(
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
                transcript=transcript,
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
                resolution=resolution,
            )
        except VoiceError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc,
                resolution=resolution,
            )

    # ── helpers ─────────────────────────────────────────────────────

    def _validate_request(
        self, request: IngressTranscribeRequest
    ) -> None:
        if request.audio.attributes.get("operational_directive"):
            raise VoiceContainmentError(
                "voice substrate MUST NEVER carry operational "
                "directives — caller passed "
                "'operational_directive' attribute."
            )

    def _build_identity(
        self,
        request: IngressTranscribeRequest,
        *,
        resolution: AuthorityResolution,
    ) -> VoiceIdentity:
        event_id = derive_event_id(
            seed=f"ingress|{request.seed}"
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
            tenant_id=resolution.tenant_id,
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
        request: IngressTranscribeRequest,
        result: IngressTranscribeResult,
        *,
        provider_name: str | None,
        error: BaseException | None,
        resolution: AuthorityResolution,
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
                tenant_id=resolution.tenant_id,
                provider_name=provider_name,
                error=type(error).__name__ if error else None,
                tenant_authority_source=resolution.source.value,
            ),
            result=result,
            error=error,
        )

    def _fail(
        self,
        kind: VoiceTraceKind,
        started_at: datetime,
        monotonic: float,
        request: IngressTranscribeRequest,
        error: BaseException,
        *,
        resolution: AuthorityResolution,
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
                tenant_id=resolution.tenant_id,
                error=type(error).__name__,
                tenant_authority_source=resolution.source.value,
            ),
            result=None,
            error=error,
        )


__all__ = ["VoiceIngressRuntime"]
