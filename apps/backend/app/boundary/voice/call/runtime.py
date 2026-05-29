"""Voice call session state machine."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from typing import Protocol, cast

from app.boundary.voice.call.turn_taking import (
    BargeinDetector,
    SilenceDetector,
)
from app.boundary.voice.contracts.requests import (
    EgressSynthesizeRequest,
    IngressTranscribeRequest,
)
from app.boundary.voice.contracts.results import (
    EgressSynthesizeResult,
    IngressTranscribeResult,
)
from app.boundary.voice.enums import AudioFormat
from app.boundary.voice.exceptions import (
    VoiceConfigurationError,
    VoiceNotFoundError,
    VoiceProviderError,
    VoiceValidationError,
)
from app.boundary.voice.models.audio import VoiceAudioHandle
from app.boundary.voice.runtime.aggregator import VoiceRuntime
from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
)
from app.identity import AuthorityContext, TenantId

_CALL_NAMESPACE = uuid.UUID("6ccf5296-7fb9-5bb9-87a6-b8bf79fbfb9d")
_TURN_NAMESPACE = uuid.UUID("27e3c3ee-f8b9-5a48-9921-4b63590542a5")

VoiceTimelineAppender = Callable[
    [str, str, str, str, Mapping[str, object]], Awaitable[None]
]


class _LanguageDetector(Protocol):
    def detect(self, text: str) -> str: ...


class VoiceCallState(StrEnum):
    IDLE = "idle"
    AWAITING_GREETING = "awaiting_greeting"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    BARGE_IN = "barge_in"
    HUMAN_HANDOFF = "human_handoff"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class VoiceCallContext:
    call_id: str
    session_id: str
    tenant_id: str
    state: VoiceCallState
    turn_count: int
    current_transcript: str | None
    last_activity: datetime
    language: str = "en"


@dataclass(frozen=True)
class VoiceCallTimelineEvent:
    call_id: str
    from_state: VoiceCallState
    to_state: VoiceCallState
    occurred_at: datetime
    reason: str
    metadata: Mapping[str, object]


class VoiceCallSessionRuntime:
    """State machine for one voice call conversation."""

    def __init__(
        self,
        *,
        voice_runtime: VoiceRuntime,
        capability_governance: GovernanceRuntime | None,
        silence_detector: SilenceDetector | None = None,
        bargein_detector: BargeinDetector | None = None,
        language_detector: _LanguageDetector | None = None,
        timeline_appender: VoiceTimelineAppender | None = None,
    ) -> None:
        if capability_governance is None:
            raise VoiceConfigurationError(
                "VoiceCallSessionRuntime requires capability_governance"
            )
        self._voice_runtime = voice_runtime
        self._capability_governance = capability_governance
        self._silence_detector = silence_detector or SilenceDetector()
        self._bargein_detector = bargein_detector or BargeinDetector()
        self._language_detector = language_detector or _default_language_detector()
        self._timeline_appender = timeline_appender
        self._contexts: dict[str, VoiceCallContext] = {}
        self._audio_chunks: dict[str, list[VoiceAudioHandle]] = {}
        self._timeline: dict[str, list[VoiceCallTimelineEvent]] = {}

    async def start_call(
        self,
        *,
        session_id: str,
        tenant_id: str,
        call_nonce: str,
    ) -> VoiceCallContext:
        call_id = derive_call_id(
            session_id=session_id,
            tenant_id=tenant_id,
            call_nonce=call_nonce,
        )
        now = datetime.now(UTC)
        context = VoiceCallContext(
            call_id=call_id,
            session_id=session_id,
            tenant_id=tenant_id,
            state=VoiceCallState.AWAITING_GREETING,
            turn_count=0,
            current_transcript=None,
            last_activity=now,
            language="en",
        )
        self._contexts[call_id] = context
        self._audio_chunks[call_id] = []
        self._timeline[call_id] = [
            VoiceCallTimelineEvent(
                call_id=call_id,
                from_state=VoiceCallState.IDLE,
                to_state=VoiceCallState.AWAITING_GREETING,
                occurred_at=now,
                reason="call_started",
                metadata={"session_id": session_id},
            )
        ]
        await self._append_session_event(
            event_type="voice_call_started",
            context=context,
            payload={"call_id": call_id},
        )
        return context

    async def handle_audio_chunk(
        self,
        *,
        call_id: str,
        audio_handle: VoiceAudioHandle,
        expected_tenant_id: str,
    ) -> VoiceCallContext:
        context = self._require_context(call_id, expected_tenant_id)
        if self._bargein_detector.is_barge_in(
            context.state, audio_handle
        ):
            return await self.handle_barge_in(
                call_id=call_id,
                expected_tenant_id=expected_tenant_id,
            )

        chunks = self._audio_chunks.setdefault(call_id, [])
        chunks.append(audio_handle)
        now = datetime.now(UTC)
        chunk_at = _chunk_time(audio_handle, now)
        if not self._silence_detector.is_utterance_complete(
            chunk_at, now
        ):
            return self._store(
                replace(
                    context,
                    state=VoiceCallState.LISTENING,
                    last_activity=now,
                )
            )

        processing = self._transition(
            context,
            VoiceCallState.PROCESSING,
            reason="utterance_complete",
            metadata={"chunk_count": len(chunks)},
        )
        transcript = await self._transcribe_utterance(
            processing,
            audio_handle,
        )
        chunks.clear()
        language = self._detect_transcript_language(
            transcript,
            fallback=processing.language,
        )
        return self._store(
            replace(
                processing,
                turn_count=processing.turn_count + 1,
                current_transcript=transcript,
                last_activity=datetime.now(UTC),
                language=language,
            )
        )

    async def deliver_response(
        self,
        *,
        call_id: str,
        response_text: str,
        governance_decision_id: str,
        expected_tenant_id: str,
    ) -> EgressSynthesizeResult:
        if not governance_decision_id:
            raise VoiceConfigurationError(
                "governance_decision_id is required before voice synthesis"
            )
        context = self._require_context(call_id, expected_tenant_id)
        decision_uuid = uuid.UUID(str(governance_decision_id))
        decision = await self._capability_governance.get_persisted_decision(
            decision_uuid,
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None or decision.decision != "allow":
            raise VoiceConfigurationError(
                "voice synthesis requires persisted ALLOW governance decision"
            )
        if not response_text:
            raise VoiceValidationError("response_text must be non-empty")

        turn_id = derive_turn_id(call_id=call_id, turn_count=context.turn_count)
        envelope = await self._voice_runtime.egress.synthesize(
            EgressSynthesizeRequest(
                text=response_text,
                target_language=context.language,
                audio_format=AudioFormat.OPUS,
                sample_rate_hz=16000,
                seed=f"voice-response|{turn_id}",
                correlation_id=call_id,
                tenant_id=expected_tenant_id,
                authority=AuthorityContext(
                    tenant_id=TenantId(expected_tenant_id),
                    capabilities=frozenset(
                        {OperationalAct.BOUNDARY_VOICE_EGRESS.value}
                    ),
                ),
                attributes={
                    "session_id": context.session_id,
                    "turn_id": turn_id,
                    "governance_decision_id": governance_decision_id,
                },
            )
        )
        if not envelope.is_ok or envelope.result is None:
            raise VoiceProviderError(
                "voice synthesis failed after governance validation"
            ) from envelope.error
        if not isinstance(envelope.result, EgressSynthesizeResult):
            raise VoiceProviderError(
                "voice synthesis returned an unexpected result type"
            )
        self._store(
            self._transition(
                context,
                VoiceCallState.SPEAKING,
                reason="response_delivered",
                metadata={
                    "turn_id": turn_id,
                    "governance_decision_id": governance_decision_id,
                },
            )
        )
        return envelope.result

    async def handle_barge_in(
        self,
        *,
        call_id: str,
        expected_tenant_id: str,
    ) -> VoiceCallContext:
        context = self._require_context(call_id, expected_tenant_id)
        barge = self._transition(
            context,
            VoiceCallState.BARGE_IN,
            reason="barge_in_detected",
            metadata={},
        )
        listening = self._transition(
            barge,
            VoiceCallState.LISTENING,
            reason="barge_in_listen",
            metadata={},
        )
        return self._store(listening)

    async def terminate_call(
        self,
        *,
        call_id: str,
        reason: str,
        expected_tenant_id: str,
    ) -> None:
        context = self._require_context(call_id, expected_tenant_id)
        terminated = self._store(
            self._transition(
                context,
                VoiceCallState.TERMINATED,
                reason=reason,
                metadata={"turn_count": context.turn_count},
            )
        )
        await self._append_session_event(
            event_type="voice_call_ended",
            context=terminated,
            payload={"call_id": call_id, "reason": reason},
        )
        del self._contexts[call_id]
        self._audio_chunks.pop(call_id, None)

    def active_call_count(self) -> int:
        return len(self._contexts)

    def get_context(self, call_id: str) -> VoiceCallContext | None:
        return self._contexts.get(call_id)

    def timeline_events(
        self, call_id: str
    ) -> tuple[VoiceCallTimelineEvent, ...]:
        return tuple(self._timeline.get(call_id, ()))

    async def _transcribe_utterance(
        self,
        context: VoiceCallContext,
        audio_handle: VoiceAudioHandle,
    ) -> str:
        turn_id = derive_turn_id(
            call_id=context.call_id,
            turn_count=context.turn_count,
        )
        envelope = await self._voice_runtime.ingress.transcribe(
            IngressTranscribeRequest(
                audio=audio_handle,
                target_language=context.language,
                seed=f"voice-utterance|{turn_id}",
                correlation_id=context.call_id,
                tenant_id=context.tenant_id,
                attributes={
                    "session_id": context.session_id,
                    "turn_id": turn_id,
                },
            )
        )
        if not envelope.is_ok or envelope.result is None:
            raise VoiceProviderError("voice transcription failed") from (
                envelope.error
            )
        if not isinstance(envelope.result, IngressTranscribeResult):
            raise VoiceProviderError(
                "voice transcription returned an unexpected result type"
            )
        if envelope.result.transcript is None:
            raise VoiceProviderError(
                "voice transcription returned no transcript"
            )
        return envelope.result.transcript.text

    def _detect_transcript_language(
        self,
        transcript: str,
        *,
        fallback: str,
    ) -> str:
        try:
            detected = self._language_detector.detect(transcript)
        except Exception:  # noqa: BLE001
            return fallback or "en"
        return detected or fallback or "en"

    def _require_context(
        self, call_id: str, expected_tenant_id: str
    ) -> VoiceCallContext:
        context = self._contexts.get(call_id)
        if context is None:
            raise VoiceNotFoundError(f"unknown voice call: {call_id}")
        if context.tenant_id != expected_tenant_id:
            raise VoiceNotFoundError(f"unknown voice call: {call_id}")
        return context

    def _transition(
        self,
        context: VoiceCallContext,
        to_state: VoiceCallState,
        *,
        reason: str,
        metadata: Mapping[str, object],
    ) -> VoiceCallContext:
        now = datetime.now(UTC)
        event = VoiceCallTimelineEvent(
            call_id=context.call_id,
            from_state=context.state,
            to_state=to_state,
            occurred_at=now,
            reason=reason,
            metadata=dict(metadata),
        )
        self._timeline.setdefault(context.call_id, []).append(event)
        return replace(
            context,
            state=to_state,
            last_activity=now,
        )

    def _store(self, context: VoiceCallContext) -> VoiceCallContext:
        self._contexts[context.call_id] = context
        return context

    async def _append_session_event(
        self,
        *,
        event_type: str,
        context: VoiceCallContext,
        payload: Mapping[str, object],
    ) -> None:
        if self._timeline_appender is None:
            return
        await self._timeline_appender(
            context.session_id,
            context.call_id,
            context.tenant_id,
            event_type,
            {"event_type": event_type, **dict(payload)},
        )


def derive_call_id(
    *,
    session_id: str,
    tenant_id: str,
    call_nonce: str,
) -> str:
    return str(
        uuid.uuid5(
            _CALL_NAMESPACE,
            f"voice-call|{session_id}|{tenant_id}|{call_nonce}",
        )
    )


def derive_turn_id(*, call_id: str, turn_count: int) -> str:
    return str(uuid.uuid5(_TURN_NAMESPACE, f"{call_id}|turn|{turn_count}"))


def _default_language_detector() -> _LanguageDetector:
    module = import_module("app.language")
    detector_type = getattr(module, "LanguageDetector")
    return cast(_LanguageDetector, detector_type())


def _chunk_time(audio_handle: VoiceAudioHandle, now: datetime) -> datetime:
    value = audio_handle.attributes.get("received_at")
    if isinstance(value, datetime):
        return value
    return now


__all__ = [
    "VoiceCallContext",
    "VoiceCallSessionRuntime",
    "VoiceCallState",
    "VoiceCallTimelineEvent",
    "derive_call_id",
    "derive_turn_id",
]
