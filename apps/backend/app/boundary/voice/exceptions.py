"""Voice-substrate exception hierarchy."""

from __future__ import annotations


class VoiceError(Exception):
    """Base voice-substrate exception."""


class VoiceConfigurationError(VoiceError):
    """Provider / persistence wiring problem at composition time."""


class VoiceValidationError(VoiceError):
    """Caller-supplied request violates the substrate contract."""


class VoiceProviderError(VoiceError):
    """Underlying STT/TTS provider failed."""


class VoiceContainmentError(VoiceError):
    """Voice operation would alter operational meaning.

    Raised when a caller asks the voice substrate to influence
    governance, mutate cognition, or inject orchestration. This
    exception is the central invariant of the voice substrate.
    """


class VoicePersistenceError(VoiceError):
    """Persistence backend rejected a write or read."""


class VoiceNotFoundError(VoiceError):
    """Read for an unknown voice artifact."""


__all__ = [
    "VoiceConfigurationError",
    "VoiceContainmentError",
    "VoiceError",
    "VoiceNotFoundError",
    "VoicePersistenceError",
    "VoiceProviderError",
    "VoiceValidationError",
]
