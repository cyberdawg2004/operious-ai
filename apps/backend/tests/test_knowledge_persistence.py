"""Knowledge persistence chronology invariants."""

from __future__ import annotations

import ast
from pathlib import Path


def test_document_version_update_helper_is_removed() -> None:
    source = Path("apps/backend/app/tenant/persistence/postgres.py").read_text(
        encoding="utf-8"
    )
    module = ast.parse(source)

    function_names = {
        node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
    }

    assert "_update_document_version_row" not in function_names
    assert "assert_version_row_unchanged_or_raise" in function_names


def test_chronology_columns_are_non_nullable_in_orm() -> None:
    source = Path("apps/backend/app/tenant/db/models.py").read_text(
        encoding="utf-8"
    )

    assert "source_approval_id: Mapped[str]" in source
    assert "content_sha256: Mapped[str]" in source
    assert "previous_version_sha256: Mapped[str | None]" in source
