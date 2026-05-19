"""Voice adapter interfaces and deterministic stub adapters.

Renamed from ``app.boundary.voice.providers`` to
``app.boundary.voice.adapters`` in PR-A3 so the package name
aligns with the constitutional ``boundary/adapters/`` apex
layout. Class names (``BaseSpeechToTextProvider`` etc.) retain
the ``Provider`` suffix for now — that semantic rename is a
separate follow-up to keep PR-A3 strictly mechanical.
"""

from app.boundary.voice.adapters.base import (
    BaseSpeechToTextProvider,
    BaseTextToSpeechProvider,
    SpeechToTextProviderRequest,
    SpeechToTextProviderResponse,
    TextToSpeechProviderRequest,
    TextToSpeechProviderResponse,
)
from app.boundary.voice.adapters.stub import (
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
