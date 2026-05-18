"""Pure-helper tests: hardening canonical serialisers."""

from __future__ import annotations

import pytest

from app.hardening.serializers import canonicalize_attributes


def test_canonicalize_attributes_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        canonicalize_attributes(["not", "a", "mapping"])  # type: ignore[arg-type]
