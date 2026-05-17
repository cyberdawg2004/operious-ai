"""Voice provider interfaces and deterministic stub providers."""

from app.boundary.voice.providers.base import (
    BaseSpeechToTextProvider,
    BaseTextToSpeechProvider,
    SpeechToTextProviderRequest,
    SpeechToTextProviderResponse,
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
)
from app.boundary.voice.providers.stub import (
    DeterministicStubSpeechToTextProvider,
    DeterministicStubTextToSpeechProvider,
)

__all__ = [
    "BaseSpeechToTextProvider",
    "BaseTextToSpeechProvider",
    "DeterministicStubSpeechToTextProvider",
    "DeterministicStubTextToSpeechProvider",
    "SpeechToTextProviderRequest",
    "SpeechToTextProviderResponse",
    "TextToSpeechProviderRequest",
    "TextToSpeechProviderResponse",
]
