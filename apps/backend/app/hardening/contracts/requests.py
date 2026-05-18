"""Typed runtime requests for the hardening substrate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from app.hardening.enums import (
    ContainmentClassification,
    FailureClassification,
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.models.ownership import AuthorityOwnershipMap
from app.identity import (
    AuthorityContext,
    check_tenant_authority_coexistence,
)


@dataclass(frozen=True, slots=True)
class ValidateAuthorityOwnershipRequest:
    """Validate that no offender is touching a forbidden concern.

    The ``observed_owners`` mapping captures, per concern, the
    set of substrates the caller has observed touching that
    concern. The validator emits a violation for each
    observed-owner that is in the boundary's ``forbidden_owners``.
    """

    observed_owners: Mapping[str, tuple[SubstrateName, ...]]
    map: AuthorityOwnershipMap | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateLineageRequest:
    """Validate lineage acyclicity / contiguity.

    Each entry of ``records`` is a `(node_id, parent_id_or_none)`
    tuple. The validator detects cycles, missing parents, and
    drift.
    """

    records: tuple[tuple[str, str | None], ...]
    scope: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateReplayRequest:
    """Compare a canonical and a candidate payload for byte-equivalence."""

    canonical_payload: Any
    candidate_payload: Any
    scope: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateReconstructionRequest:
    """Compare original artifacts against reconstructed artifacts."""

    original_payload: Any
    reconstructed_payload: Any
    scope: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateOrderingRequest:
    """Validate that an iterable is in deterministic ordering.

    The validator runs the supplied ``key_fn`` over the items
    and asserts that the resulting key sequence is sorted.
    """

    items: tuple[Any, ...]
    key_fn: Callable[[Any], Any]
    scope: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DetectContaminationRequest:
    """Scan substrate paths for forbidden cross-substrate imports.

    ``substrate_paths`` is a tuple of `(substrate, path)` pairs.
    ``forbidden_modules`` is the regex-ish list of module
    prefixes the substrate must not import.
    """

    substrate: SubstrateName
    substrate_path: str
    forbidden_module_prefixes: tuple[str, ...]
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AuditDependenciesRequest:
    """Build a substrate-dependency graph and flag forbidden edges."""

    substrate_paths: tuple[tuple[SubstrateName, str], ...]
    forbidden_edges: tuple[tuple[SubstrateName, SubstrateName], ...] = ()
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidateSurvivabilityRequest:
    """Compare expected-vs-observed counts of persisted records."""

    expected_count: int
    survived_count: int
    scope: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecordFailureRequest:
    """Classify and record a substrate failure.

    The substrate refuses to take recovery action. The record is
    write-once; the caller (operator / dashboard) decides what
    to do next.
    """

    substrate: SubstrateName
    classification: FailureClassification
    containment: ContainmentClassification
    severity: HardeningSeverity
    summary: str
    error_class_name: str
    seed: str
    evidence: tuple[str, ...] = ()
    correlation_id: str | None = None
    tenant_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    authority: AuthorityContext | None = None

    def __post_init__(self) -> None:
        check_tenant_authority_coexistence(
            contract_name="RecordFailureRequest",
            authority=self.authority,
            tenant_id=self.tenant_id,
        )


@dataclass(frozen=True, slots=True)
class ClassifyContainmentRequest:
    """Classify whether a known failure stayed inside its boundary.

    The caller supplies the substrate the failure originated in
    and a tuple of substrates that were observed reacting to the
    failure. The validator returns CONTAINED if the only
    observer is the originating substrate, LEAKED otherwise.
    """

    originating_substrate: SubstrateName
    observers: tuple[SubstrateName, ...]
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "AuditDependenciesRequest",
    "ClassifyContainmentRequest",
    "DetectContaminationRequest",
    "RecordFailureRequest",
    "ValidateAuthorityOwnershipRequest",
    "ValidateLineageRequest",
    "ValidateOrderingRequest",
    "ValidateReconstructionRequest",
    "ValidateReplayRequest",
    "ValidateSurvivabilityRequest",
]
