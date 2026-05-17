"""Pure lineage-construction helpers for memory artifacts."""

from __future__ import annotations

from app.organizational_intelligence.exceptions import (
    IntelligenceLineageError,
)
from app.organizational_intelligence.identity import (
    MemoryArtifactId,
    derive_pattern_lineage_id,
)
from app.organizational_intelligence.models.memory import (
    PatternLineage,
)


def build_lineage_for_root(
    *,
    artifact_id: MemoryArtifactId,
) -> PatternLineage:
    """Build the lineage for a fresh root artifact."""
    return PatternLineage(
        lineage_id=derive_pattern_lineage_id(
            root_artifact_id=artifact_id
        ),
        artifact_id=artifact_id,
        root_artifact_id=artifact_id,
        parent_artifact_id=None,
        ancestor_artifact_ids=(),
        depth=0,
    )


def build_lineage_for_successor(
    *,
    artifact_id: MemoryArtifactId,
    parent_lineage: PatternLineage,
) -> PatternLineage:
    """Extend an existing lineage by one supersession generation."""
    if artifact_id in parent_lineage.ancestor_artifact_ids:
        raise IntelligenceLineageError(
            "cycle detected: proposed artifact id is an ancestor"
        )
    if artifact_id == parent_lineage.artifact_id:
        raise IntelligenceLineageError(
            "cycle detected: proposed artifact id equals parent"
        )
    ancestors = (
        parent_lineage.ancestor_artifact_ids
        + (parent_lineage.artifact_id,)
    )
    return PatternLineage(
        lineage_id=parent_lineage.lineage_id,
        artifact_id=artifact_id,
        root_artifact_id=parent_lineage.root_artifact_id,
        parent_artifact_id=parent_lineage.artifact_id,
        ancestor_artifact_ids=ancestors,
        depth=parent_lineage.depth + 1,
    )


def extend_lineage(
    *,
    parent_lineage: PatternLineage,
    new_artifact_id: MemoryArtifactId,
) -> PatternLineage:
    return build_lineage_for_successor(
        artifact_id=new_artifact_id,
        parent_lineage=parent_lineage,
    )


__all__ = [
    "build_lineage_for_root",
    "build_lineage_for_successor",
    "extend_lineage",
]
