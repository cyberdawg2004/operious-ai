"""PR_RT10 concurrent voice load tests with delayed stub providers."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi import WebSocketException

from app.api.v1.routers.voice import stream_voice_session
from app.boundary.voice import (
    AudioFormat,
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
    InMemoryVoicePersistence,
    SpeechToTextProviderRequest,
    SpeechToTextProviderResponse,
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
    VoiceEgressRuntime,
    VoiceIngressRuntime,
    VoiceRuntime,
    VoiceAudioHandle,
)
from app.boundary.voice.call import (
    VOICE_CAPACITY_KEY,
    VoiceCallSessionRuntime,
    VoiceCapacityCounter,
)
from app.governance.enums import Decision
from tests.load.test_voice_capacity import (
    _app_with_capacity as _capacity_app_with_capacity,
)
from tests.test_voice_call_runtime import _governance, _persist_decision

pytestmark = pytest.mark.load

SIMULATED_STT_LATENCY_MS = 150
SIMULATED_TTS_LATENCY_MS = 80
CONCURRENT_CALLS = 10


@dataclass(frozen=True)
class _CallTiming:
    setup_ms: float
    first_response_ms: float
    turn_ms: float
    completion_ms: float


class _FakeCapacityRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self._lock = threading.Lock()

    async def ping(self) -> bool:
        return True

    async def get(self, name: str) -> int | None:
        with self._lock:
            return self.values.get(name)

    async def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: object,
    ) -> int:
        del numkeys
        key = str(keys_and_args[0])
        with self._lock:
            current = self.values.get(key, 0)
            if "INCR" in script:
                limit = int(keys_and_args[1])
                if current < limit:
                    self.values[key] = current + 1
                    return 1
                return 0
            if "DECR" in script and current > 0:
                self.values[key] = current - 1
                return self.values[key]
            self.values[key] = max(0, current)
            return self.values[key]


class _AlwaysCompleteSilenceDetector:
    def is_utterance_complete(
        self,
        last_chunk_at: datetime,
        now: datetime,
    ) -> bool:
        del last_chunk_at, now
        return True


class _StaticLanguageDetector:
    def detect(self, text: str) -> str:
        del text
        return "en"


class _AdmissionOnlyWebSocket:
    query_params = {"tenant": "tenant-load"}


@pytest.mark.asyncio
async def test_voice_concurrent_calls_under_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_provider_latency(monkeypatch)
    governance, _ = _governance(Decision.ALLOW)
    decision_id = await _persist_decision(governance, tenant_id="tenant-load")
    runtime = _voice_call_runtime(governance=governance)
    counter = VoiceCapacityCounter(
        redis_client=_FakeCapacityRedis(),
        limit=CONCURRENT_CALLS,
        key=VOICE_CAPACITY_KEY,
    )

    timings = await asyncio.gather(
        *[
            _run_runtime_call(
                runtime=runtime,
                counter=counter,
                index=index,
                governance_decision_id=str(decision_id),
            )
            for index in range(CONCURRENT_CALLS)
        ]
    )

    assert len(timings) == CONCURRENT_CALLS
    setup = [timing.setup_ms for timing in timings]
    first_response = [timing.first_response_ms for timing in timings]
    turn = [timing.turn_ms for timing in timings]
    completion = [timing.completion_ms for timing in timings]

    setup_p95 = _percentile(setup, 0.95)
    first_response_p95 = _percentile(first_response, 0.95)
    assert setup_p95 < 500, (
        f"call setup p95 {setup_p95:.0f}ms exceeds 500ms target"
    )
    assert first_response_p95 < 1000, (
        "first response p95 "
        f"{first_response_p95:.0f}ms exceeds 1000ms target"
    )

    print(
        "Voice concurrent timing summary: "
        f"setup_p50={_percentile(setup, 0.50):.0f}ms, "
        f"setup_p95={setup_p95:.0f}ms, "
        f"first_response_p50={_percentile(first_response, 0.50):.0f}ms, "
        f"first_response_p95={first_response_p95:.0f}ms, "
        f"turn_p50={_percentile(turn, 0.50):.0f}ms, "
        f"turn_p95={_percentile(turn, 0.95):.0f}ms, "
        f"completion_p50={_percentile(completion, 0.50):.0f}ms, "
        f"completion_p95={_percentile(completion, 0.95):.0f}ms"
    )


def test_voice_admission_under_overload() -> None:
    limit = CONCURRENT_CALLS
    _, counter = _capacity_app_with_capacity(limit=limit)
    rejected_latencies: list[float] = []
    accepted = 0

    for _ in range(limit):
        assert asyncio.run(counter.try_acquire()) is True
        accepted += 1

    assert asyncio.run(counter.current_count()) == limit

    rejected = 0
    for index in range(5):
        started = time.perf_counter()
        with pytest.raises(WebSocketException) as exc_info:
            asyncio.run(
                stream_voice_session(
                    websocket=_AdmissionOnlyWebSocket(),  # type: ignore[arg-type]
                    session_id=f"rejected-{index}",
                    capacity=counter,
                )
            )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert exc_info.value.code == 1013
        assert elapsed_ms < 100, f"overload rejection took {elapsed_ms:.0f}ms"
        rejected_latencies.append(elapsed_ms)
        rejected += 1

    for _ in range(limit):
        asyncio.run(counter.release())
    assert accepted == limit
    assert rejected == 5
    assert asyncio.run(counter.current_count()) == 0
    print(
        "Voice overload timing summary: "
        f"accepted={limit}, rejected={rejected}, "
        f"rejection_p50={_percentile(rejected_latencies, 0.50):.0f}ms, "
        f"rejection_p95={_percentile(rejected_latencies, 0.95):.0f}ms"
    )


def _patch_provider_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    original_transcribe = DeterministicStubSpeechToTextProvider.transcribe
    original_synthesize = DeterministicStubTextToSpeechProvider.synthesize

    async def delayed_transcribe(
        self: DeterministicStubSpeechToTextProvider,
        request: SpeechToTextProviderRequest,
    ) -> SpeechToTextProviderResponse:
        await asyncio.sleep(SIMULATED_STT_LATENCY_MS / 1000.0)
        return await original_transcribe(self, request)

    async def delayed_synthesize(
        self: DeterministicStubTextToSpeechProvider,
        request: TextToSpeechProviderRequest,
    ) -> TextToSpeechProviderResponse:
        await asyncio.sleep(SIMULATED_TTS_LATENCY_MS / 1000.0)
        return await original_synthesize(self, request)

    monkeypatch.setattr(
        DeterministicStubSpeechToTextProvider,
        "transcribe",
        delayed_transcribe,
    )
    monkeypatch.setattr(
        DeterministicStubTextToSpeechProvider,
        "synthesize",
        delayed_synthesize,
    )


def _voice_call_runtime(
    *,
    governance: object,
) -> VoiceCallSessionRuntime:
    persistence = InMemoryVoicePersistence()
    voice_runtime = VoiceRuntime(
        ingress=VoiceIngressRuntime(
            provider=DeterministicStubSpeechToTextProvider(),
            persistence=persistence,
        ),
        egress=VoiceEgressRuntime(
            provider=DeterministicStubTextToSpeechProvider(),
            persistence=persistence,
            capability_governance=governance,
        ),
    )
    return VoiceCallSessionRuntime(
        voice_runtime=voice_runtime,
        capability_governance=governance,
        silence_detector=_AlwaysCompleteSilenceDetector(),
        language_detector=_StaticLanguageDetector(),
    )


async def _run_runtime_call(
    *,
    runtime: VoiceCallSessionRuntime,
    counter: VoiceCapacityCounter,
    index: int,
    governance_decision_id: str,
) -> _CallTiming:
    setup_started = time.perf_counter()
    acquired = await counter.try_acquire()
    assert acquired is True
    context = await runtime.start_call(
        session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"voice-runtime-{index}")),
        tenant_id="tenant-load",
        call_nonce=f"voice-runtime-{index}",
    )
    setup_ms = (time.perf_counter() - setup_started) * 1000.0
    response_started = time.perf_counter()
    context = await runtime.handle_audio_chunk(
        call_id=context.call_id,
        audio_handle=_audio_handle(index),
        expected_tenant_id="tenant-load",
    )
    first_response_ms = (time.perf_counter() - response_started) * 1000.0
    assert context.turn_count == 1
    turn_started = time.perf_counter()
    await runtime.deliver_response(
        call_id=context.call_id,
        response_text="I can help with that charging issue.",
        governance_decision_id=governance_decision_id,
        expected_tenant_id="tenant-load",
    )
    turn_ms = (time.perf_counter() - turn_started) * 1000.0
    await runtime.terminate_call(
        call_id=context.call_id,
        reason="load_test_complete",
        expected_tenant_id="tenant-load",
    )
    await counter.release()
    completion_ms = (time.perf_counter() - setup_started) * 1000.0
    return _CallTiming(
        setup_ms=setup_ms,
        first_response_ms=first_response_ms,
        turn_ms=turn_ms,
        completion_ms=completion_ms,
    )


def _audio_handle(index: int) -> VoiceAudioHandle:
    return VoiceAudioHandle(
        handle=f"voice-load-audio:{index}",
        audio_format=AudioFormat.PCM_S16LE,
        sample_rate_hz=16000,
        duration_ms=100,
        language="en",
        attributes={"transcript": f"customer charging issue number {index}"},
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, int(len(ordered) * percentile + 0.999999) - 1),
    )
    return ordered[index]
