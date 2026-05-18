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
from app.boundary.translation.serializers import (
    canonicalize_attributes,
    canonicalize_payload,
    content_fingerprint,
)


def test_normalize_text_collapses_whitespace_and_trims() -> None:
    out, record = normalize_text("  Hello   world\t  ", language="en")
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
    assert check.status is SemanticPreservationStatus.DRIFTED
    assert "escalate" in check.canonical_tokens_missing


def test_semantic_preservation_suspicious_when_token_introduced() -> None:
    check = check_semantic_preservation(
        canonical_text="please respond",
        candidate_text="por favor escalate",
    )
    assert check.status is SemanticPreservationStatus.SUSPICIOUS
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


def test_canonicalize_attributes_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        canonicalize_attributes(["not", "a", "mapping"])  # type: ignore[arg-type]


def test_canonicalize_payload_accepts_mixed_type_mapping_keys() -> None:
    """Doctrine F-28: Mapping sorts MUST be `_string_key`-projected so
    cross-type comparison does not raise. Native key types are preserved;
    only the *sort order* uses the projection."""
    canonical = canonicalize_payload({1: "a", "b": 2})
    assert isinstance(canonical, dict)
    assert canonical[1] == "a"
    assert canonical["b"] == 2


def test_canonicalize_payload_nested_mixed_keys_do_not_raise() -> None:
    canonical = canonicalize_payload({"outer": {3: "x", "y": 4}})
    assert canonical["outer"][3] == "x"
    assert canonical["outer"]["y"] == 4


def test_canonicalize_payload_is_byte_stable_across_invocations() -> None:
    """Same input produces byte-identical fingerprint regardless of
    construction order — constitutional replay-evidence requirement."""
    payload_a = {"b": [3, 1, 2], "a": {"y": 1, "x": 2}}
    payload_b = {"a": {"x": 2, "y": 1}, "b": [3, 1, 2]}
    assert content_fingerprint(payload_a) == content_fingerprint(payload_b)


def test_canonicalize_attributes_uses_string_key_projection() -> None:
    """Mixed-type-key attributes must canonicalize without raising — the
    doctrine binding under F-28 for boundary/translation."""
    result = canonicalize_attributes({"alpha": 1, "beta": {3: "x", "y": 4}})
    assert result["alpha"] == 1
    assert result["beta"][3] == "x"
    assert result["beta"]["y"] == 4
