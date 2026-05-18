"""2.5-H: ``OperationClassification`` taxonomy invariants.

Pinned properties:

* the catalog is closed (no silent additions) and the values are
  unique,
* every value is lowercase and dot-separated,
* the canonical metadata key is the only public string the
  substrates agree on,
* the module is a leaf — no imports from sibling substrates other
  than stdlib.
"""

from __future__ import annotations

import ast
import pathlib
import re

from app.governance.classification import (
    BOUNDARY_OPERATION_CLASSIFICATION_KEY,
    OperationClassification,
)


_VALUE_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$|^generic$")


def test_classification_values_are_unique() -> None:
    values = [c.value for c in OperationClassification]
    assert len(values) == len(set(values))


def test_classification_values_are_dot_separated_lowercase() -> None:
    for c in OperationClassification:
        assert _VALUE_RE.match(c.value), (
            f"{c.name} value {c.value!r} violates the canonical "
            f"naming doctrine (lowercase, dot-separated)"
        )


def test_canonical_metadata_key_pinned() -> None:
    assert (
        BOUNDARY_OPERATION_CLASSIFICATION_KEY
        == "boundary.operation_classification"
    )


def test_classification_module_is_a_leaf() -> None:
    """The module must not import from any sibling substrate. Only
    stdlib imports are allowed (``from __future__``, ``enum``).
    """
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "app"
        / "governance"
        / "classification.py"
    )
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    forbidden_prefixes = (
        "app.boundary",
        "app.session",
        "app.coordination",
        "app.arbitration",
        "app.hardening",
        "app.supervisor",
        "app.agents",
        "app.organizational_intelligence",
        "app.api",
        "app.services",
        "app.repositories",
        "app.middleware",
        "app.observability",
        "app.dependencies",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes), (
                    f"classification.py must not import {alias.name!r}"
                )
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(forbidden_prefixes), (
                f"classification.py must not import from "
                f"{node.module!r}"
            )


def test_generic_is_explicit_fallback() -> None:
    """``GENERIC`` is the explicit unclassified fallback — it MUST
    appear in the catalog so producers can stamp it deliberately
    rather than drifting to ``None``.
    """
    assert OperationClassification.GENERIC == "generic"
