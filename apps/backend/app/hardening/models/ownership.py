"""Semantic-authority-ownership models.

The `AuthorityOwnershipMap` is the **canonical declaration** of
which substrate owns which semantic concern. Hardening
validators consult this map to detect contamination.

This is a structural assertion. The substrate refuses to allow
two boundaries to claim the same concern (the constructor raises).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.hardening.enums import SubstrateName
from app.hardening.identity import (
    SemanticAuthorityBoundaryId,
    derive_boundary_id,
)


@dataclass(frozen=True, slots=True)
class SemanticAuthorityBoundary:
    """One declarative authority-boundary record.

    A boundary asserts: "the *concern* is owned by *owner*."

    Attributes:
        boundary_id:        Stable id derived from
                             ``(concern, owner)``.
        concern:            The semantic concern in question
                             (e.g. ``"approval"``,
                             ``"escalation"``, ``"continuity"``).
        owner:              The substrate that owns the concern.
        description:        Free-form documentation.
        forbidden_owners:   Substrates that MUST NOT claim this
                             concern. Used by the validator to
                             produce explicit violation findings.
        attributes:         Canonical metadata payload.
    """

    boundary_id: SemanticAuthorityBoundaryId
    concern: str
    owner: SubstrateName
    description: str
    forbidden_owners: tuple[SubstrateName, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.concern:
            raise ValueError(
                "SemanticAuthorityBoundary.concern must be non-empty"
            )
        if not self.description:
            raise ValueError(
                "SemanticAuthorityBoundary.description must be "
                "non-empty"
            )
        if self.owner in self.forbidden_owners:
            raise ValueError(
                "SemanticAuthorityBoundary.owner cannot also be "
                "in forbidden_owners"
            )


@dataclass(frozen=True, slots=True)
class AuthorityOwnershipMap:
    """Canonical map of authority boundaries.

    Construction-time checks:

    * No two boundaries may claim the same concern.
    * Iteration is sorted by concern (deterministic).
    """

    boundaries: tuple[SemanticAuthorityBoundary, ...]

    def __post_init__(self) -> None:
        seen: dict[str, SubstrateName] = {}
        for b in self.boundaries:
            if b.concern in seen:
                raise ValueError(
                    f"duplicate authority boundary for concern "
                    f"{b.concern!r}: existing owner={seen[b.concern].value}"
                )
            seen[b.concern] = b.owner

    @classmethod
    def build(
        cls,
        rows: Iterable[
            tuple[
                str,
                SubstrateName,
                str,
                tuple[SubstrateName, ...],
            ]
        ],
    ) -> AuthorityOwnershipMap:
        """Build a canonical map from `(concern, owner, description, forbidden)` tuples."""
        boundaries: list[SemanticAuthorityBoundary] = []
        for concern, owner, description, forbidden in rows:
            boundaries.append(
                SemanticAuthorityBoundary(
                    boundary_id=derive_boundary_id(
                        concern=concern, owner=owner.value
                    ),
                    concern=concern,
                    owner=owner,
                    description=description,
                    forbidden_owners=tuple(
                        sorted(
                            set(forbidden),
                            key=lambda s: s.value,
                        )
                    ),
                )
            )
        boundaries.sort(key=lambda b: b.concern)
        return cls(boundaries=tuple(boundaries))

    def owner_for(
        self, concern: str
    ) -> SubstrateName | None:
        for b in self.boundaries:
            if b.concern == concern:
                return b.owner
        return None

    def boundary_for(
        self, concern: str
    ) -> SemanticAuthorityBoundary | None:
        for b in self.boundaries:
            if b.concern == concern:
                return b
        return None

    def concerns(self) -> tuple[str, ...]:
        return tuple(b.concern for b in self.boundaries)


# ─── Canonical Operious authority-ownership map ─────────────────────


CANONICAL_AUTHORITY_OWNERSHIP_MAP: AuthorityOwnershipMap = (
    AuthorityOwnershipMap.build(
        [
            (
                "operational_restrictions",
                SubstrateName.GOVERNANCE,
                "Governance owns operational restrictions / "
                "compliance / forbidden behaviour.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                    SubstrateName.SUPERVISOR,
                ),
            ),
            (
                "topology_authorization",
                SubstrateName.COORDINATION_TOPOLOGY,
                "Topology owns allowed-path / chain-depth / "
                "boundary-crossing authority.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.COORDINATION,
                    SubstrateName.GOVERNANCE,
                ),
            ),
            (
                "policy_authorization",
                SubstrateName.COORDINATION_POLICY,
                "Policy owns coordination-authorization rules.",
                (
                    SubstrateName.COORDINATION_TOPOLOGY,
                    SubstrateName.GOVERNANCE,
                ),
            ),
            (
                "coordination_dispatch",
                SubstrateName.COORDINATION,
                "Coordination owns deterministic communication "
                "dispatch.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.SUPERVISOR,
                ),
            ),
            (
                "conflict_interpretation",
                SubstrateName.ARBITRATION,
                "Arbitration owns deterministic interpretation of "
                "conflicting operational signals.",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.SUPERVISOR,
                ),
            ),
            (
                "operational_continuity",
                SubstrateName.SESSION,
                "Session owns operational continuity and "
                "lineage reconstruction.",
                (
                    SubstrateName.COORDINATION,
                    SubstrateName.AGENTS,
                ),
            ),
            (
                "external_translation",
                SubstrateName.BOUNDARY,
                "Boundary owns translation between deterministic "
                "internal and nondeterministic external systems.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.GOVERNANCE,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                ),
            ),
            (
                "multilingual_translation",
                SubstrateName.BOUNDARY_TRANSLATION,
                "Boundary translation owns customer-language "
                "↔ canonical-English projection at the edge only.",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                    SubstrateName.AGENTS,
                ),
            ),
            (
                "voice_translation",
                SubstrateName.BOUNDARY_VOICE,
                "Boundary voice owns STT/TTS at the edge only.",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                    SubstrateName.AGENTS,
                ),
            ),
            (
                "evaluation",
                SubstrateName.SUPERVISOR,
                "Supervision owns evaluation / scoring / anomaly "
                "detection — read-only.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.GOVERNANCE,
                ),
            ),
            (
                "memory_evolution",
                SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                "Organizational intelligence owns governed "
                "memory evolution. Asynchronous only.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.GOVERNANCE,
                    SubstrateName.SUPERVISOR,
                ),
            ),
            (
                "tonality_classification",
                SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                "Tonality classification is owned by the "
                "intelligence substrate; tonality NEVER owns "
                "communication policy or governance.",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.AGENTS,
                ),
            ),
            (
                "communication_pattern_retrieval",
                SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                "Communication pattern retrieval is read-only "
                "over APPROVED patterns.",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.AGENTS,
                ),
            ),
            (
                "operational_approval",
                SubstrateName.HUMAN,
                "Operational approval / SOP authority / governance "
                "approval / memory adoption are HUMAN-owned.",
                (
                    SubstrateName.AGENTS,
                    SubstrateName.GOVERNANCE,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                    SubstrateName.SUPERVISOR,
                ),
            ),
            (
                "execution",
                SubstrateName.AGENTS,
                "Execution is owned by the agent runtime "
                "(deterministic).",
                (
                    SubstrateName.GOVERNANCE,
                    SubstrateName.SUPERVISOR,
                    SubstrateName.ORGANIZATIONAL_INTELLIGENCE,
                ),
            ),
        ]
    )
)


__all__ = [
    "AuthorityOwnershipMap",
    "CANONICAL_AUTHORITY_OWNERSHIP_MAP",
    "SemanticAuthorityBoundary",
]
