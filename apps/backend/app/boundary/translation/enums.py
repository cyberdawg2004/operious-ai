"""Translation-substrate wire-format vocabulary.

Translation is **boundary infrastructure**. It translates
representation only — it must NEVER change governance,
escalation, authority, compliance, or SOP semantics.

Pinned wire values are guarded by
`tests/test_translation_invariants.py`.
"""

from __future__ import annotations

from enum import StrEnum


class TranslationDirection(StrEnum):
    """Direction of translation flow."""

    INGRESS = "ingress"
    EGRESS = "egress"


class TranslationStatus(StrEnum):
    """Lifecycle of a translation envelope."""

    PENDING = "pending"
    NORMALIZED = "normalized"
    TRANSLATED = "translated"
    VALIDATED = "validated"
    LOCALIZED = "localized"
    COMPLETED = "completed"
    REJECTED = "rejected"
    ERRORED = "errored"


class TranslationProviderKind(StrEnum):
    """Translation provider type."""

    IDENTITY = "identity"
    DETERMINISTIC_STUB = "deterministic_stub"
    EXTERNAL = "external"


class SemanticPreservationStatus(StrEnum):
    """Outcome of semantic-preservation validation."""

    PRESERVED = "preserved"
    DRIFTED = "drifted"
    SUSPICIOUS = "suspicious"
    UNVERIFIABLE = "unverifiable"


class LocalizationFormality(StrEnum):
    """Bounded vocabulary for localization formality.

    Descriptive metadata only. Localization MUST NOT touch
    governance / escalation semantics.
    """

    NEUTRAL = "neutral"
    FORMAL = "formal"
    INFORMAL = "informal"


class TranslationFindingKind(StrEnum):
    """Closed vocabulary for translation findings."""

    OK = "ok"
    UNVERIFIED_PROVIDER = "unverified_provider"
    SEMANTIC_DRIFT = "semantic_drift"
    NORMALIZATION_DRIFT = "normalization_drift"
    PROHIBITED_TOKEN_LOSS = "prohibited_token_loss"
    PROHIBITED_TOKEN_INJECTED = "prohibited_token_injected"
    REPLAY_DRIFT = "replay_drift"


class TranslationTraceKind(StrEnum):
    """One trace kind per translation-runtime method."""

    INGRESS_TRANSLATE = "ingress_translate"
    EGRESS_LOCALIZE = "egress_localize"
    GET_INGRESS = "get_ingress"
    GET_EGRESS = "get_egress"


CANONICAL_LANGUAGE = "en"
"""All canonical operational cognition occurs in English."""


__all__ = [
    "CANONICAL_LANGUAGE",
    "LocalizationFormality",
    "SemanticPreservationStatus",
    "TranslationDirection",
    "TranslationFindingKind",
    "TranslationProviderKind",
    "TranslationStatus",
    "TranslationTraceKind",
]
