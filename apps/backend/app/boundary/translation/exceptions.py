"""Translation-substrate exception hierarchy.

Public translation runtime methods NEVER raise; the classes
below are internal discriminators that populate envelope errors.

The discipline: translation MUST NEVER alter governance,
escalation, or SOP meaning. Any caller that asks the substrate
to do so receives `TranslationContainmentError` inside the
envelope.
"""

from __future__ import annotations


class TranslationError(Exception):
    """Base translation-substrate exception."""


class TranslationConfigurationError(TranslationError):
    """Provider / persistence wiring problem at composition time."""


class TranslationValidationError(TranslationError):
    """Caller-supplied request violates the substrate contract."""


class TranslationProviderError(TranslationError):
    """Underlying translation/STT/TTS provider failed."""


class TranslationContainmentError(TranslationError):
    """Translation request would alter operational semantics.

    Raised when a caller asks the translation substrate to alter
    governance, escalation, authority, compliance, or SOP
    semantics. This exception is the central invariant of the
    translation substrate.
    """


class TranslationPersistenceError(TranslationError):
    """Persistence backend rejected a write or read."""


class TranslationNotFoundError(TranslationError):
    """Read for an unknown translation artifact."""


__all__ = [
    "TranslationConfigurationError",
    "TranslationContainmentError",
    "TranslationError",
    "TranslationNotFoundError",
    "TranslationPersistenceError",
    "TranslationProviderError",
    "TranslationValidationError",
]
