"""Pure deterministic candidate-pattern extractor.

Stateless. Given the caller-supplied summary + body + observation
seed, it builds a `CandidatePattern` with deterministic id and
content fingerprint. No autonomous extraction from external data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.organizational_intelligence.enums import (
    IntelligenceScope,
    MemoryArtifactKind,
)
from app.organizational_intelligence.identity import (
    derive_candidate_pattern_id,
)
from app.organizational_intelligence.models.memory import (
    CandidatePattern,
)
from app.organizational_intelligence.serializers.canonical import (
    canonicalize_attributes,
    content_fingerprint,
)


_EXTRACTOR_SIGNATURE = "deterministic.candidate_extractor.v1"


class DeterministicCandidateExtractor:
    """Pure deterministic candidate extractor."""

    __slots__ = ()

    @property
    def signature(self) -> str:
        return _EXTRACTOR_SIGNATURE

    def extract(  # noqa: PLR0913
        self,
        *,
        observation_seed: str,
        summary: str,
        body: str,
        kind: MemoryArtifactKind,
        evidence: tuple[str, ...],
        extracted_at: datetime,
        scope: IntelligenceScope,
        tenant_id: str | None,
        attributes: Mapping[str, Any] | None = None,
    ) -> CandidatePattern:
        if not observation_seed:
            raise ValueError(
                "extract requires non-empty observation_seed"
            )
        return CandidatePattern(
            candidate_id=derive_candidate_pattern_id(
                observation_seed=observation_seed
            ),
            observation_seed=observation_seed,
            kind=kind,
            summary=summary,
            body=body,
            content_fingerprint=content_fingerprint(body),
            evidence=tuple(sorted(set(evidence))),
            extracted_at=extracted_at,
            extractor_signature=_EXTRACTOR_SIGNATURE,
            scope=scope,
            tenant_id=tenant_id,
            attributes=canonicalize_attributes(
                attributes or {}
            ),
        )


__all__ = ["DeterministicCandidateExtractor"]
