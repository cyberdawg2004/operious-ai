"""Translation pure-helper tests."""

from __future__ import annotations

import pytest

from app.boundary.translation.normalization.normalizer import (
    normalize_text,
)
from app.boundary.translation.replay.verifier import (
    verify_translation_replay,
)
from app.boundary.translation.semantic_validation.validator import (
    SemanticPreservationStatus,
    check_semantic_preservation,
)


def test_normalize_text_collapses_whitespace_and_trims() -> None:
    out, record = normalize_text(
        "  Hello   world\t  ", language="en"
    )
    assert out == "Hello world"
    assert "trim" in record.steps
    assert "collapse_whitespace" in record.steps


def test_normalize_text_rejects_nul_bytes() -> None:
    with pytest.raises(ValueError):
        normalize_text("\x00", language="en")


def test_semantic_preservation_clean_when_tokens_match() -> None:
    check = check_semantic_preservation(
        canonical_text="please escalate",
        candidate_text="por favor escalate",
    )
    assert check.is_preserved


def test_semantic_preservation_drifted_when_tokens_lost() -> None:
    check = check_semantic_preservation(
        canonical_text="please escalate",
        candidate_text="please respond",
    )
    assert (
        check.status is SemanticPreservationStatus.DRIFTED
    )
    assert "escalate" in check.canonical_tokens_missing


def test_semantic_preservation_suspicious_when_token_introduced() -> (
    None
):
    check = check_semantic_preservation(
        canonical_text="please respond",
        candidate_text="por favor escalate",
    )
    assert (
        check.status
        is SemanticPreservationStatus.SUSPICIOUS
    )
    assert "escalate" in check.introduced_governance_tokens


def test_verify_translation_replay_recomputes_fingerprints() -> None:
    from datetime import UTC, datetime

    from app.boundary.translation.identity import (
        derive_replay_id,
    )
    from app.boundary.translation.models.replay import (
        TranslationReplay,
    )
    from app.boundary.translation.serializers.canonical import (
        text_fingerprint,
    )

    canonical_fp = text_fingerprint("Hello", language="en")
    boundary_fp = text_fingerprint("Hola", language="es")
    replay = TranslationReplay(
        replay_id=derive_replay_id(seed="x"),
        seed="x",
        canonical_fingerprint=canonical_fp,
        boundary_fingerprint=boundary_fp,
        provider_name="identity",
        captured_at=datetime.now(UTC),
    )
    assert verify_translation_replay(
        replay=replay,
        canonical_text="Hello",
        canonical_language="en",
        boundary_text="Hola",
        boundary_language="es",
    )
    assert not verify_translation_replay(
        replay=replay,
        canonical_text="Hello!",
        canonical_language="en",
        boundary_text="Hola",
        boundary_language="es",
    )
