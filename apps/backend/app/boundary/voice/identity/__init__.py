"""Voice-substrate identity primitives."""

from __future__ import annotations

import uuid
import itertools
from typing import NewType


VoiceEventId = NewType("VoiceEventId", uuid.UUID)
VoiceTranscriptId = NewType("VoiceTranscriptId", uuid.UUID)
VoiceSynthesisId = NewType("VoiceSynthesisId", uuid.UUID)
VoiceLineageId = NewType("VoiceLineageId", uuid.UUID)
VoiceCorrelationId = NewType("VoiceCorrelationId", uuid.UUID)
VoiceTraceId = NewType("VoiceTraceId", uuid.UUID)
VoiceProviderId = NewType("VoiceProviderId", uuid.UUID)
VoiceReplayId = NewType("VoiceReplayId", uuid.UUID)


_EVENT_NAMESPACE = uuid.UUID(
    "030fdc2a-0001-4001-8001-200000000001"
)
_TRANSCRIPT_NAMESPACE = uuid.UUID(
    "030fdc2a-0002-4002-8002-200000000002"
)
_SYNTHESIS_NAMESPACE = uuid.UUID(
    "030fdc2a-0003-4003-8003-200000000003"
)
_LINEAGE_NAMESPACE = uuid.UUID(
    "030fdc2a-0004-4004-8004-200000000004"
)
_CORRELATION_NAMESPACE = uuid.UUID(
    "030fdc2a-0005-4005-8005-200000000005"
)
_TRACE_NAMESPACE = uuid.UUID(
    "030fdc2a-0006-4006-8006-200000000006"
)
_PROVIDER_NAMESPACE = uuid.UUID(
    "030fdc2a-0007-4007-8007-200000000007"
)
_REPLAY_NAMESPACE = uuid.UUID(
    "030fdc2a-0008-4008-8008-200000000008"
)
_RUNTIME_COUNTER = itertools.count()


def generate_event_id() -> VoiceEventId:
    return VoiceEventId(uuid.uuid5(_EVENT_NAMESPACE, _runtime_seed("event")))


def generate_transcript_id() -> VoiceTranscriptId:
    return VoiceTranscriptId(uuid.uuid5(_TRANSCRIPT_NAMESPACE, _runtime_seed("transcript")))


def generate_synthesis_id() -> VoiceSynthesisId:
    return VoiceSynthesisId(uuid.uuid5(_SYNTHESIS_NAMESPACE, _runtime_seed("synthesis")))


def generate_lineage_id() -> VoiceLineageId:
    return VoiceLineageId(uuid.uuid5(_LINEAGE_NAMESPACE, _runtime_seed("lineage")))


def generate_correlation_id() -> VoiceCorrelationId:
    return VoiceCorrelationId(uuid.uuid5(_CORRELATION_NAMESPACE, _runtime_seed("correlation")))


def generate_trace_id() -> VoiceTraceId:
    return VoiceTraceId(uuid.uuid5(_TRACE_NAMESPACE, _runtime_seed("trace")))


def generate_replay_id() -> VoiceReplayId:
    return VoiceReplayId(uuid.uuid5(_REPLAY_NAMESPACE, _runtime_seed("replay")))


def _runtime_seed(label: str) -> str:
    return f"runtime|{label}|{next(_RUNTIME_COUNTER)}"


def derive_event_id(*, seed: str) -> VoiceEventId:
    if not seed:
        raise ValueError("derive_event_id requires non-empty seed")
    return VoiceEventId(uuid.uuid5(_EVENT_NAMESPACE, seed))


def derive_transcript_id(*, seed: str) -> VoiceTranscriptId:
    if not seed:
        raise ValueError(
            "derive_transcript_id requires non-empty seed"
        )
    return VoiceTranscriptId(
        uuid.uuid5(_TRANSCRIPT_NAMESPACE, seed)
    )


def derive_synthesis_id(*, seed: str) -> VoiceSynthesisId:
    if not seed:
        raise ValueError(
            "derive_synthesis_id requires non-empty seed"
        )
    return VoiceSynthesisId(
        uuid.uuid5(_SYNTHESIS_NAMESPACE, seed)
    )


def derive_lineage_id(*, seed: str) -> VoiceLineageId:
    if not seed:
        raise ValueError(
            "derive_lineage_id requires non-empty seed"
        )
    return VoiceLineageId(
        uuid.uuid5(_LINEAGE_NAMESPACE, seed)
    )


def derive_correlation_id(*, seed: str) -> VoiceCorrelationId:
    if not seed:
        raise ValueError(
            "derive_correlation_id requires non-empty seed"
        )
    return VoiceCorrelationId(
        uuid.uuid5(_CORRELATION_NAMESPACE, seed)
    )


def derive_trace_id(*, seed: str) -> VoiceTraceId:
    if not seed:
        raise ValueError(
            "derive_trace_id requires non-empty seed"
        )
    return VoiceTraceId(uuid.uuid5(_TRACE_NAMESPACE, seed))


def derive_provider_id(*, name: str) -> VoiceProviderId:
    if not name:
        raise ValueError(
            "derive_provider_id requires non-empty name"
        )
    return VoiceProviderId(
        uuid.uuid5(_PROVIDER_NAMESPACE, name)
    )


def derive_replay_id(*, seed: str) -> VoiceReplayId:
    if not seed:
        raise ValueError(
            "derive_replay_id requires non-empty seed"
        )
    return VoiceReplayId(uuid.uuid5(_REPLAY_NAMESPACE, seed))


__all__ = [
    "VoiceCorrelationId",
    "VoiceEventId",
    "VoiceLineageId",
    "VoiceProviderId",
    "VoiceReplayId",
    "VoiceSynthesisId",
    "VoiceTraceId",
    "VoiceTranscriptId",
    "derive_correlation_id",
    "derive_event_id",
    "derive_lineage_id",
    "derive_provider_id",
    "derive_replay_id",
    "derive_synthesis_id",
    "derive_trace_id",
    "derive_transcript_id",
    "generate_correlation_id",
    "generate_event_id",
    "generate_lineage_id",
    "generate_replay_id",
    "generate_synthesis_id",
    "generate_trace_id",
    "generate_transcript_id",
]
