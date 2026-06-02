"""Grounding checks for customer-facing reply claims."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.knowledge.identity import as_document_id
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeReviewStatus,
)
from app.tenant.persistence import TenantConfigurationRepository


@dataclass(frozen=True, slots=True)
class GroundingCheckRequest:
    tenant_id: str
    reply_segments: Sequence[Mapping[str, Any]]
    evidence: Sequence[Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class GroundingCheckResult:
    allowed: bool
    trace: Mapping[str, Any]


class GroundingChecker(Protocol):
    async def check(self, request: GroundingCheckRequest) -> GroundingCheckResult:
        """Return whether every claim is covered by approved span citations."""
        ...


class CitationCoverageGroundingChecker:
    """Verify claim citations resolve to approved/current knowledge spans."""

    def __init__(
        self,
        *,
        document_repository: TenantConfigurationRepository,
    ) -> None:
        self._documents = document_repository

    async def check(self, request: GroundingCheckRequest) -> GroundingCheckResult:
        rank_map = _rank_map(request.evidence)
        approved: list[dict[str, Any]] = []
        ungrounded: list[dict[str, Any]] = []
        claim_count = 0
        for index, segment in enumerate(request.reply_segments):
            if _segment_kind(segment) != "claim":
                continue
            claim_count += 1
            text = _segment_text(segment)
            ranks = _segment_ranks(segment)
            if not ranks:
                ungrounded.append(
                    {
                        "segment_index": index,
                        "claim": text,
                        "reason": "uncited_claim",
                        "citation_ranks": [],
                    }
                )
                continue
            missing_reasons: list[str] = []
            for rank in ranks:
                citation = rank_map.get(rank)
                if citation is None:
                    missing_reasons.append(f"rank_{rank}_missing")
                    continue
                resolution = await self._resolve_citation(
                    tenant_id=request.tenant_id,
                    citation=citation,
                )
                if resolution is None:
                    missing_reasons.append(f"rank_{rank}_unresolvable")
                    continue
                approved.append({**resolution, "claim": text})
            if missing_reasons:
                ungrounded.append(
                    {
                        "segment_index": index,
                        "claim": text,
                        "reason": "unresolvable_citation",
                        "details": missing_reasons,
                        "citation_ranks": ranks,
                    }
                )
        trace = {
            "schema_version": "2.1",
            "status": "grounded" if not ungrounded else "ungrounded",
            "claim_count": claim_count,
            "approved_knowledge_found": approved,
            "ungrounded_claims": ungrounded,
        }
        return GroundingCheckResult(allowed=not ungrounded, trace=trace)

    async def _resolve_citation(
        self,
        *,
        tenant_id: str,
        citation: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if _citation_status(citation, "document_status") != "active":
            return None
        if _citation_status(citation, "document_review_status") != "approved":
            return None
        if (_int_value(citation.get("citation_schema_version")) or 0) < 2:
            return None
        document_id = _text(citation.get("document_id"))
        document_version = _int_value(citation.get("document_version"))
        char_start = _int_value(citation.get("char_start"))
        char_end = _int_value(citation.get("char_end"))
        if (
            document_id is None
            or document_version is None
            or char_start is None
            or char_end is None
            or char_start < 0
            or char_end <= char_start
        ):
            return None
        try:
            document = await self._documents.get_knowledge_document(
                as_document_id(document_id),
                expected_tenant_id=tenant_id,
            )
        except (TypeError, ValueError):
            return None
        if document is None:
            return None
        if document.tenant_id != tenant_id:
            return None
        if document.status is not TenantKnowledgeDocumentStatus.ACTIVE:
            return None
        if document.review_status is not TenantKnowledgeReviewStatus.APPROVED:
            return None
        if document.version != document_version:
            return None
        content = document.content.strip()
        if char_end > len(content):
            return None
        span = content[char_start:char_end]
        if not span.strip():
            return None
        return {
            "rank": _int_value(citation.get("rank")),
            "document_id": document_id,
            "document_version": document_version,
            "document_status": document.status.value,
            "document_review_status": document.review_status.value,
            "title": document.title,
            "char_start": char_start,
            "char_end": char_end,
            "span_sha256": hashlib.sha256(span.encode("utf-8")).hexdigest(),
            "safe_excerpt": _text(citation.get("safe_excerpt")),
        }


class StaticGroundingChecker:
    """Test seam that swaps behind the same GroundingChecker interface."""

    def __init__(self, *, allowed: bool, trace: Mapping[str, Any] | None = None) -> None:
        self._allowed = allowed
        self._trace = dict(trace or {"schema_version": "test"})

    async def check(self, request: GroundingCheckRequest) -> GroundingCheckResult:
        del request
        trace = {
            "schema_version": "test",
            "status": "grounded" if self._allowed else "ungrounded",
            **self._trace,
        }
        return GroundingCheckResult(allowed=self._allowed, trace=trace)


def _rank_map(
    evidence: Sequence[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    ranks: dict[int, Mapping[str, Any]] = {}
    for item in evidence:
        rank = _int_value(item.get("rank"))
        if rank is not None:
            ranks[rank] = item
    return ranks


def _segment_kind(segment: Mapping[str, Any]) -> str:
    return str(segment.get("kind") or "").strip().lower()


def _segment_text(segment: Mapping[str, Any]) -> str:
    return str(segment.get("text") or "").strip()


def _segment_ranks(segment: Mapping[str, Any]) -> list[int]:
    value = segment.get("citation_ranks")
    if not isinstance(value, list):
        return []
    ranks: list[int] = []
    for item in cast(list[object], value):
        rank = _int_value(item)
        if rank is not None and rank > 0:
            ranks.append(rank)
    return list(dict.fromkeys(ranks))


def _citation_status(citation: Mapping[str, Any], key: str) -> str:
    return str(citation.get(key) or "").strip().lower()


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


__all__ = [
    "CitationCoverageGroundingChecker",
    "GroundingCheckRequest",
    "GroundingCheckResult",
    "GroundingChecker",
    "StaticGroundingChecker",
]
