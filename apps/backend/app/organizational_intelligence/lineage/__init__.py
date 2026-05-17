"""Memory-artifact lineage helpers (pure ancestry construction)."""

from app.organizational_intelligence.lineage.tracker import (
    build_lineage_for_root,
    build_lineage_for_successor,
    extend_lineage,
)

__all__ = [
    "build_lineage_for_root",
    "build_lineage_for_successor",
    "extend_lineage",
]
