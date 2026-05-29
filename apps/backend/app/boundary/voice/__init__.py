"""Operious AI — voice boundary substrate.

Voice → STT → translation → canonical cognition (ingress).
Canonical cognition → translation → TTS → voice (egress).

The voice substrate is **boundary infrastructure** ONLY. It
MUST NEVER influence governance, mutate cognition, change
operational meaning, or inject orchestration logic.
"""

from app.boundary.voice.contracts.requests import (
    EgressSynthesizeRequest,
    IngressTranscribeRequest,
)
from app.boundary.voice.contracts.results import (
    EgressSynthesizeResult,
    IngressTranscribeResult,
)
from app.boundary.voice.egress.runtime import VoiceEgressRuntime
from app.boundary.voice.enums import (
    AudioFormat,
    VoiceDirection,
    VoiceFindingKind,
    VoiceProviderKind,
    VoiceStatus,
    VoiceTraceKind,
)
from app.boundary.voice.envelopes import VoiceEnvelope
from app.boundary.voice.exceptions import (
    VoiceConfigurationError,
    VoiceContainmentError,
    VoiceError,
    VoiceNotFoundError,
    VoicePersistenceError,
    VoiceProviderError,
    VoiceValidationError,
)
from app.boundary.voice.identity import (
    VoiceCorrelationId,
    VoiceEventId,
    VoiceLineageId,
    VoiceProviderId,
    VoiceReplayId,
    VoiceSynthesisId,
    VoiceTraceId,
    VoiceTranscriptId,
)
from app.boundary.voice.ingress.runtime import (
    VoiceIngressRuntime,
)
from app.boundary.voice.models import (
    VoiceAudioHandle,
    VoiceIdentity,
    VoiceLineage,
    VoiceLineageEntry,
    VoiceReplay,
    VoiceSynthesis,
    VoiceTranscript,
)
from app.boundary.voice.normalization.normalizer import (
    VoiceNormalizer,
)
from app.boundary.voice.persistence import (
    InMemoryVoicePersistence,
    PostgresVoicePersistence,
    VoiceEgressRecord,
    VoiceIngressRecord,
    VoicePersistenceProtocol,
)
from app.boundary.voice.adapters import (
    BaseSpeechToTextProvider,
    BaseTextToSpeechProvider,
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
    SpeechToTextProviderRequest,
    SpeechToTextProviderResponse,
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
)
from app.boundary.voice.replay.verifier import (
    verify_voice_replay,
)
from app.boundary.voice.runtime.aggregator import VoiceRuntime
from app.boundary.voice.traces import (
    VoiceTrace,
    VoiceTraceContext,
)

__all__ = [
    "AudioFormat",
    "BaseSpeechToTextProvider",
    "BaseTextToSpeechProvider",
    "DeterministicStubSpeechToTextProvider",
    "DeterministicStubTextToSpeechProvider",
    "EgressSynthesizeRequest",
    "EgressSynthesizeResult",
    "InMemoryVoicePersistence",
    "IngressTranscribeRequest",
    "IngressTranscribeResult",
    "PostgresVoicePersistence",
    "SpeechToTextProviderRequest",
    "SpeechToTextProviderResponse",
    "TextToSpeechProviderRequest",
    "TextToSpeechProviderResponse",
    "VoiceAudioHandle",
    "VoiceConfigurationError",
    "VoiceContainmentError",
    "VoiceCorrelationId",
    "VoiceDirection",
    "VoiceEgressRecord",
    "VoiceEgressRuntime",
    "VoiceEnvelope",
    "VoiceError",
    "VoiceEventId",
    "VoiceFindingKind",
    "VoiceIdentity",
    "VoiceIngressRecord",
    "VoiceIngressRuntime",
    "VoiceLineage",
    "VoiceLineageEntry",
    "VoiceLineageId",
    "VoiceNormalizer",
    "VoiceNotFoundError",
    "VoicePersistenceError",
    "VoicePersistenceProtocol",
    "VoiceProviderError",
    "VoiceProviderId",
    "VoiceProviderKind",
    "VoiceReplay",
    "VoiceReplayId",
    "VoiceRuntime",
    "VoiceStatus",
    "VoiceSynthesis",
    "VoiceSynthesisId",
    "VoiceTrace",
    "VoiceTraceContext",
    "VoiceTraceId",
    "VoiceTraceKind",
    "VoiceTranscript",
    "VoiceTranscriptId",
    "VoiceValidationError",
    "verify_voice_replay",
]
