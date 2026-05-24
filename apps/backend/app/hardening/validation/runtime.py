"""`HardeningRuntime` — the apex composition root.

Public methods are async + never-raising. They produce
`HardeningEnvelope` outputs containing immutable result objects
plus a `HardeningTrace`. Errors land inside the envelope.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
    gate_or_deny,
)
from app.identity import request_authority_resolution
from app.hardening.audits.recorder import (
    HardeningAuditRecorder,
)
from app.hardening.contracts.requests import (
    AuditDependenciesRequest,
    ClassifyContainmentRequest,
    DetectContaminationRequest,
    RecordFailureRequest,
    ValidateAuthorityOwnershipRequest,
    ValidateLineageRequest,
    ValidateOrderingRequest,
    ValidateReconstructionRequest,
    ValidateReplayRequest,
    ValidateSurvivabilityRequest,
)
from app.hardening.contracts.results import (
    AuditDependenciesResult,
    ClassifyContainmentResult,
    DetectContaminationResult,
    RecordFailureResult,
    ValidateAuthorityOwnershipResult,
    ValidateLineageResult,
    ValidateOrderingResult,
    ValidateReconstructionResult,
    ValidateReplayResult,
    ValidateSurvivabilityResult,
)
from app.hardening.enums import (
    HardeningStatus,
    HardeningTraceKind,
    IntegrityStatus,
)
from app.hardening.envelopes import HardeningEnvelope
from app.hardening.exceptions import (
    HardeningContainmentError,
    HardeningError,
)
from app.hardening.identity import (
    derive_audit_id as derive_audit_id,
    derive_correlation_id,
    derive_failure_record_id,
    derive_trace_id,
    generate_correlation_id as generate_correlation_id,
    generate_trace_id,
)
from app.hardening.integrity.contamination import (
    detect_contamination,
)
from app.hardening.integrity.dependency import (
    audit_dependencies,
)
from app.hardening.integrity.ordering import validate_ordering
from app.hardening.isolation.containment import (
    classify_containment,
)
from app.hardening.lineage.validator import validate_lineage
from app.hardening.models.containment import (
    SemanticContainmentTrace,
)
from app.hardening.models.failure import (
    FailureContainmentRecord,
)
from app.hardening.persistence.repository import (
    HardeningPersistenceProtocol,
)
from app.hardening.replay.integrity import (
    validate_replay_equivalence,
)
from app.hardening.replay.reconstruction import (
    validate_reconstruction,
)
from app.hardening.semantic.validator import (
    validate_authority_ownership,
)
from app.hardening.survivability.validator import (
    validate_survivability,
)
from app.hardening.traces.trace import HardeningTrace

_RUNTIME_NAMESPACE = uuid.UUID("01087ec0-0009-4009-8009-000000000009")


class HardeningRuntime:
    """Apex hardening runtime.

    Methods are observational — they validate, classify, record.
    They MUST NOT mutate runtime behaviour. Any caller that asks
    the runtime to recover, dispatch, or auto-correct receives a
    `HardeningContainmentError` inside the envelope.
    """

    def __init__(
        self,
        *,
        persistence: HardeningPersistenceProtocol,
        recorder: HardeningAuditRecorder | None = None,
        runtime_instance_id: uuid.UUID | None = None,
        capability_governance: GovernanceRuntime | None = None,
    ) -> None:
        self._persistence = persistence
        self._recorder = recorder or HardeningAuditRecorder()
        self._runtime_instance_id = (
            runtime_instance_id
            or _derive_runtime_instance_id(
                persistence=persistence,
                recorder=self._recorder,
                capability_governance=capability_governance,
            )
        )
        self._sequence = 0
        # 2.75-\u03b1: capability legality gate. Inert when None.
        self._capability_governance = capability_governance

    @property
    def persistence(self) -> HardeningPersistenceProtocol:
        return self._persistence

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    # ── Validators ──────────────────────────────────────────────────

    async def validate_authority_ownership(
        self,
        request: ValidateAuthorityOwnershipRequest,
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_AUTHORITY_OWNERSHIP
        started_at, monotonic = self._mark_start()
        try:
            violations = validate_authority_ownership(
                observed_owners=request.observed_owners,
                map_=request.map,
                detected_at=started_at,
            )
            ended_at = datetime.now(UTC)
            containment = SemanticContainmentTrace(
                correlation_id=derive_correlation_id(
                    seed=self._correlation_seed(
                        kind, request.correlation_id
                    )
                ),
                checked_concerns=tuple(
                    sorted(request.observed_owners.keys())
                ),
                violations=violations,
                started_at=started_at,
                ended_at=ended_at,
            )
            audit = self._recorder.assemble(
                seed=self._audit_seed(kind, request.correlation_id),
                kind=kind,
                status=HardeningStatus.COMPLETED,
                findings=(),
                started_at=started_at,
                ended_at=ended_at,
                summary=(
                    "authority-ownership clean"
                    if not violations
                    else f"{len(violations)} authority violations"
                ),
                correlation_id=request.correlation_id,
            )
            await self._persistence.write_audit(audit)
            result = ValidateAuthorityOwnershipResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                audit=audit,
                containment=containment,
                violations=violations,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def validate_lineage(
        self, request: ValidateLineageRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_LINEAGE
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.scope or "",
            )
            findings, status = validate_lineage(
                records=request.records,
                seed=seed,
                detected_at=started_at,
            )
            ended_at = datetime.now(UTC)
            audit = self._recorder.assemble(
                seed=seed,
                kind=kind,
                status=HardeningStatus.COMPLETED,
                findings=findings,
                started_at=started_at,
                ended_at=ended_at,
                summary=(
                    "lineage integrity passed"
                    if status is IntegrityStatus.PASSED
                    else f"{len(findings)} lineage findings"
                ),
                correlation_id=request.correlation_id,
            )
            await self._persistence.write_audit(audit)
            result = ValidateLineageResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                audit=audit,
                integrity_status=status,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def validate_replay_equivalence(
        self, request: ValidateReplayRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_REPLAY
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.scope or "",
            )
            finding = validate_replay_equivalence(
                canonical_payload=request.canonical_payload,
                candidate_payload=request.candidate_payload,
                seed=seed,
                scope=request.scope,
                detected_at=started_at,
            )
            ended_at = datetime.now(UTC)
            result = ValidateReplayResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                finding=finding,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def validate_reconstruction(
        self, request: ValidateReconstructionRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_RECONSTRUCTION
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.scope or "",
            )
            finding = validate_reconstruction(
                original_payload=request.original_payload,
                reconstructed_payload=request.reconstructed_payload,
                seed=seed,
                scope=request.scope,
                detected_at=started_at,
            )
            ended_at = datetime.now(UTC)
            result = ValidateReconstructionResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                finding=finding,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def validate_ordering(
        self, request: ValidateOrderingRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_ORDERING
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.scope or "",
            )
            findings, status = validate_ordering(
                items=request.items,
                key_fn=request.key_fn,
                seed=seed,
                detected_at=started_at,
                scope=request.scope,
            )
            ended_at = datetime.now(UTC)
            audit = self._recorder.assemble(
                seed=seed,
                kind=kind,
                status=HardeningStatus.COMPLETED,
                findings=findings,
                started_at=started_at,
                ended_at=ended_at,
                summary=(
                    "ordering deterministic"
                    if status is IntegrityStatus.PASSED
                    else "ordering nondeterminism detected"
                ),
                correlation_id=request.correlation_id,
            )
            await self._persistence.write_audit(audit)
            result = ValidateOrderingResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                audit=audit,
                integrity_status=status,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def detect_contamination(
        self, request: DetectContaminationRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.DETECT_CONTAMINATION
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.substrate.value,
            )
            findings, status = detect_contamination(
                substrate=request.substrate,
                substrate_path=request.substrate_path,
                forbidden_module_prefixes=(
                    request.forbidden_module_prefixes
                ),
                seed=seed,
                detected_at=started_at,
                source_lines_by_path=request.metadata.get(
                    "source_lines_by_path"
                ),
            )
            ended_at = datetime.now(UTC)
            audit = self._recorder.assemble(
                seed=seed,
                kind=kind,
                status=HardeningStatus.COMPLETED,
                findings=findings,
                started_at=started_at,
                ended_at=ended_at,
                summary=(
                    "no contamination detected"
                    if status is IntegrityStatus.PASSED
                    else f"{len(findings)} contamination findings"
                ),
                correlation_id=request.correlation_id,
            )
            await self._persistence.write_audit(audit)
            result = DetectContaminationResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata={
                    k: v
                    for k, v in request.metadata.items()
                    if k != "source_lines_by_path"
                },
                audit=audit,
                integrity_status=status,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def audit_dependencies(
        self, request: AuditDependenciesRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.AUDIT_DEPENDENCIES
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind, request.correlation_id
            )
            finding = audit_dependencies(
                substrate_paths=request.substrate_paths,
                forbidden_edges=request.forbidden_edges,
                seed=seed,
                detected_at=started_at,
                source_lines_by_substrate=request.metadata.get(
                    "source_lines_by_substrate"
                ),
            )
            ended_at = datetime.now(UTC)
            result = AuditDependenciesResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata={
                    k: v
                    for k, v in request.metadata.items()
                    if k != "source_lines_by_substrate"
                },
                finding=finding,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def validate_survivability(
        self, request: ValidateSurvivabilityRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.VALIDATE_SURVIVABILITY
        started_at, monotonic = self._mark_start()
        try:
            seed = self._audit_seed(
                kind,
                request.correlation_id,
                extra=request.scope or "",
            )
            finding = validate_survivability(
                expected_count=request.expected_count,
                survived_count=request.survived_count,
                seed=seed,
                scope=request.scope,
                detected_at=started_at,
            )
            ended_at = datetime.now(UTC)
            result = ValidateSurvivabilityResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                finding=finding,
                survivability_status=finding.status,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def record_failure(
        self, request: RecordFailureRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.RECORD_FAILURE
        started_at, monotonic = self._mark_start()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate. Inert when None.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.HARDENING_RECORD_FAILURE,
            authority=request.authority,
            resolution=resolution,
            actor="hardening_runtime",
        )
        if denial is not None:
            return self._fail(
                kind, started_at, monotonic, request, denial
            )
        try:
            if not request.seed:
                raise HardeningContainmentError(
                    "record_failure requires non-empty seed"
                )
            record = FailureContainmentRecord(
                record_id=derive_failure_record_id(
                    seed=request.seed
                ),
                substrate=request.substrate,
                classification=request.classification,
                containment=request.containment,
                severity=request.severity,
                summary=request.summary,
                recorded_at=started_at,
                error_class_name=request.error_class_name,
                evidence=tuple(
                    sorted(set(request.evidence))
                ),
                correlation_id=request.correlation_id,
                tenant_id=resolution.tenant_id,
                attributes=dict(request.metadata),
            )
            await self._persistence.write_failure_record(
                record
            )
            ended_at = datetime.now(UTC)
            result = RecordFailureResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                record=record,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    async def classify_containment(
        self, request: ClassifyContainmentRequest
    ) -> HardeningEnvelope:
        kind = HardeningTraceKind.CLASSIFY_CONTAINMENT
        started_at, monotonic = self._mark_start()
        try:
            classification = classify_containment(
                originating_substrate=request.originating_substrate,
                observers=request.observers,
            )
            ended_at = datetime.now(UTC)
            result = ClassifyContainmentResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=self._latency_ms(monotonic),
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                classification=classification,
            )
            return self._envelope(
                kind, started_at, ended_at, monotonic,
                request, result, error=None,
            )
        except HardeningError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc
            )

    # ── helpers ─────────────────────────────────────────────────────

    def _mark_start(self) -> tuple[datetime, float]:
        return datetime.now(UTC), time.perf_counter()

    @staticmethod
    def _latency_ms(start_perf: float) -> float:
        return (
            time.perf_counter() - start_perf
        ) * 1000.0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _correlation_seed(
        self,
        kind: HardeningTraceKind,
        correlation_id: str | None,
    ) -> str:
        return (
            f"{kind.value}|{correlation_id or 'none'}|"
            f"{self._runtime_instance_id}|{self._sequence + 1}"
        )

    def _audit_seed(
        self,
        kind: HardeningTraceKind,
        correlation_id: str | None,
        *,
        extra: str = "",
    ) -> str:
        return (
            f"{kind.value}|{correlation_id or 'none'}|"
            f"{self._runtime_instance_id}|{self._sequence + 1}|"
            f"{extra}"
        )

    def _envelope(
        self,
        kind: HardeningTraceKind,
        started_at: datetime,
        ended_at: datetime,
        monotonic: float,
        request: object,
        result: object,
        *,
        error: BaseException | None,
    ) -> HardeningEnvelope:
        sequence = self._sequence
        correlation_id = getattr(request, "correlation_id", None)
        request_id = getattr(request, "request_id", None)
        # P2-C: resolve authority via the contract-agnostic adapter so
        # every emitted trace carries the same provenance attribution
        # that the runtime entry computed.
        resolution = request_authority_resolution(request)

        if correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{correlation_id}|{request_id}|"
                    f"{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        trace = HardeningTrace(
            trace_id=trace_id,
            kind=kind,
            runtime_instance_id=self._runtime_instance_id,
            sequence=sequence,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=self._latency_ms(monotonic),
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            audit_seed=getattr(result, "audit", None)
            and getattr(result.audit, "seed", None),  # type: ignore[union-attr]
            error=type(error).__name__ if error else None,
            tenant_authority_source=resolution.source.value,
        )
        return HardeningEnvelope(
            trace=trace,
            result=result,
            error=error,
        )

    def _fail(
        self,
        kind: HardeningTraceKind,
        started_at: datetime,
        monotonic: float,
        request: object,
        error: BaseException,
    ) -> HardeningEnvelope:
        ended_at = datetime.now(UTC)
        sequence = self._next_sequence()
        correlation_id = getattr(request, "correlation_id", None)
        request_id = getattr(request, "request_id", None)
        resolution = request_authority_resolution(request)
        if correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{correlation_id}|{request_id}|"
                    f"err|{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        trace = HardeningTrace(
            trace_id=trace_id,
            kind=kind,
            runtime_instance_id=self._runtime_instance_id,
            sequence=sequence,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=self._latency_ms(monotonic),
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=resolution.tenant_id,
            error=type(error).__name__,
            tenant_authority_source=resolution.source.value,
        )
        return HardeningEnvelope(
            trace=trace, result=None, error=error
        )


def _derive_runtime_instance_id(
    *,
    persistence: object,
    recorder: object,
    capability_governance: object | None,
) -> uuid.UUID:
    governance_type = type(capability_governance)
    seed = "|".join(
        (
            "hardening_runtime",
            type(persistence).__module__,
            type(persistence).__qualname__,
            type(recorder).__module__,
            type(recorder).__qualname__,
            (
                governance_type.__module__
                if capability_governance is not None
                else "<none>"
            ),
            (
                governance_type.__qualname__
                if capability_governance is not None
                else "<none>"
            ),
        )
    )
    return uuid.uuid5(_RUNTIME_NAMESPACE, seed)


__all__ = ["HardeningRuntime"]
