"""Pin translation-substrate wire-format vocabulary."""

from __future__ import annotations

from app.boundary.translation.enums import (
    CANONICAL_LANGUAGE,
    LocalizationFormality,
    SemanticPreservationStatus,
    TranslationDirection,
    TranslationFindingKind,
    TranslationProviderKind,
    TranslationStatus,
    TranslationTraceKind,
)


def test_canonical_language_is_english() -> None:
    assert CANONICAL_LANGUAGE == "en"


def test_direction_pinned() -> None:
    assert {member.value for member in TranslationDirection} == {
        "ingress",
        "egress",
    }


def test_status_pinned() -> None:
    assert {member.value for member in TranslationStatus} == {
        "pending",
        "normalized",
        "translated",
        "validated",
        "localized",
        "completed",
        "rejected",
        "errored",
    }


def test_provider_kind_pinned() -> None:
    assert {
        member.value for member in TranslationProviderKind
    } == {"identity", "deterministic_stub", "external"}


def test_preservation_status_pinned() -> None:
    assert {
        member.value for member in SemanticPreservationStatus
    } == {
        "preserved",
        "drifted",
        "suspicious",
        "unverifiable",
    }


def test_finding_kind_pinned() -> None:
    assert {
        member.value for member in TranslationFindingKind
    } == {
        "ok",
        "unverified_provider",
        "semantic_drift",
        "normalization_drift",
        "prohibited_token_loss",
        "prohibited_token_injected",
        "replay_drift",
    }


def test_trace_kind_pinned() -> None:
    assert {member.value for member in TranslationTraceKind} == {
        "ingress_translate",
        "egress_localize",
        "get_ingress",
        "get_egress",
    }


def test_formality_pinned() -> None:
    assert {member.value for member in LocalizationFormality} == {
        "neutral",
        "formal",
        "informal",
    }
