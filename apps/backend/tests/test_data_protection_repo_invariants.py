"""At-rest data-protection wiring invariant.

``PostgresBoundaryPersistence`` and ``PostgresResolutionProposalPersistence``
both gate encryption of sensitive JSON/text fields
(``canonical_payload['text']``, ``proposed_customer_reply``, ``draft_body``,
...) on a ``data_protection`` constructor argument. If a composition-root
call site forgets to pass it, that record is written (and read) plaintext
at rest with no error — a silent at-rest encryption bypass.

Every construction of these two classes inside ``app/`` (i.e. outside
test code) MUST pass a ``data_protection=`` keyword argument. This does not
assert the value is non-``None`` (unit tests for the repositories
legitimately construct them with ``data_protection=None``); it only closes
off "forgot to wire it at all", which is the bug class this invariant
guards against.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

_BACKEND_APP: Final[Path] = Path(__file__).parent.parent / "app"

_GUARDED_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "PostgresBoundaryPersistence",
        "PostgresResolutionProposalPersistence",
    }
)


def _app_files() -> list[Path]:
    return sorted(_BACKEND_APP.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize(
    "module_file",
    _app_files(),
    ids=lambda p: str(p.relative_to(_BACKEND_APP)),
)
def test_guarded_repository_constructions_pass_data_protection(
    module_file: Path,
) -> None:
    tree = _parse(module_file)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id not in _GUARDED_CLASSES:
            continue
        if not any(kw.arg == "data_protection" for kw in node.keywords):
            offenders.append(f"{func.id}(...) at line {node.lineno}")
    assert not offenders, (
        f"{module_file.relative_to(_BACKEND_APP)} constructs guarded "
        f"repositories without data_protection=: {offenders}. Every "
        f"{sorted(_GUARDED_CLASSES)} construction in app/ must pass "
        "data_protection= explicitly (use the module's "
        "_data_protection_service(session) helper) to avoid silently "
        "storing sensitive fields plaintext at rest."
    )
