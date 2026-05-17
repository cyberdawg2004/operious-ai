"""Canonicalisation discipline tests.

* Determinism: identical inputs → byte-identical outputs.
* Key-order invariance: input order does not affect output order.
* Fingerprint stability: identical canonical payload → identical
  fingerprint.
* Drift detectability: differing payloads → differing fingerprints.
"""

from __future__ import annotations

from app.boundary.normalization.canonicalize import (
    canonicalize_metadata,
    canonicalize_payload,
    content_fingerprint,
)


def test_canonicalize_payload_preserves_primitives() -> None:
    assert canonicalize_payload(1) == 1
    assert canonicalize_payload("a") == "a"
    assert canonicalize_payload(None) is None
    assert canonicalize_payload(True) is True


def test_canonicalize_payload_sorts_mapping_keys() -> None:
    payload = {"b": 1, "a": 2, "c": 3}
    canonical = canonicalize_payload(payload)
    assert list(canonical.keys()) == ["a", "b", "c"]


def test_canonicalize_payload_recursively_sorts() -> None:
    payload = {
        "outer": {"z": 1, "a": 2},
        "list": [{"y": 1, "x": 2}],
    }
    canonical = canonicalize_payload(payload)
    assert list(canonical["outer"].keys()) == ["a", "z"]
    assert list(canonical["list"][0].keys()) == ["x", "y"]


def test_canonicalize_metadata_typed_wrapper() -> None:
    canonical = canonicalize_metadata({"b": 1, "a": 2})
    assert list(canonical.keys()) == ["a", "b"]


def test_canonicalize_payload_handles_bytes() -> None:
    assert canonicalize_payload(b"hello") == "hello"


def test_canonicalize_payload_coerces_unknown_types() -> None:
    class Custom:
        def __str__(self) -> str:
            return "custom"

    assert canonicalize_payload(Custom()) == "custom"


def test_content_fingerprint_is_stable() -> None:
    a = {"a": 1, "b": [1, 2, {"x": 1, "y": 2}]}
    b = {"b": [1, 2, {"y": 2, "x": 1}], "a": 1}
    assert content_fingerprint(a) == content_fingerprint(b)


def test_content_fingerprint_changes_with_value() -> None:
    a = {"a": 1}
    b = {"a": 2}
    assert content_fingerprint(a) != content_fingerprint(b)


def test_content_fingerprint_changes_with_extra_field() -> None:
    a = {"a": 1}
    b = {"a": 1, "b": 2}
    assert content_fingerprint(a) != content_fingerprint(b)
