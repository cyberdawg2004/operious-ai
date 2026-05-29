"""`TranslationEgressRuntime` — canonical-English → customer-language."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from app.governance.capability import (
    GovernanceRuntime,
    OperationalAct,
    gate_or_deny,
)
from app.core.deterministic_identity import derive_runtime_id
from app.identity import (
    AuthorityResolution,
    request_authority_resolution,
)
from app.boundary.translation.contracts.requests import (
    EgressLocalizeRequest,
)
from app.boundary.translation.contracts.results import (
    EgressLocalizeResult,
)
from app.boundary.translation.enums import (
    CANONICAL_LANGUAGE,
    TranslationDirection,
    TranslationFindingKind,
    TranslationStatus,
    TranslationTraceKind,
)
from app.boundary.translation.envelopes import (
    TranslationEnvelope,
)
from app.boundary.translation.exceptions import (
    TranslationConfigurationError,
    TranslationContainmentError,
    TranslationError,
    TranslationProviderError,
    TranslationValidationError,
)
from app.boundary.translation.identity import (
    TranslationCorrelationId,
    derive_correlation_id,
    derive_lineage_id,
    derive_replay_id,
    derive_trace_id,
    derive_translation_id,
    generate_trace_id,
)
from app.boundary.translation.models.identity import (
    TranslationIdentity,
)
from app.boundary.translation.models.lineage import (
    TranslationLineageEntry,
)
from app.boundary.translation.models.localization import (
    LocalizationMetadata,
)
from app.boundary.translation.models.payload import (
    TranslationPayload,
)
from app.boundary.translation.models.replay import (
    TranslationReplay,
)
from app.boundary.translation.models.preservation import (
    SemanticPreservationCheck,
)
from app.boundary.translation.models.validation import (
    TranslationFinding,
    TranslationValidation,
)
from app.boundary.translation.normalization.normalizer import (
    BoundaryNormalizer,
)
from app.boundary.translation.persistence.records import (
    EgressLocalizationRecord,
)
from app.boundary.translation.persistence.repository import (
    TranslationPersistenceProtocol,
)
from app.boundary.translation.adapters.base import (
    BaseTranslationProvider,
    TranslationProviderRequest,
)
from app.boundary.translation.semantic_validation.validator import (
    SemanticPreservationValidator,
)
from app.boundary.translation.serializers.canonical import (
    text_fingerprint,
)
from app.boundary.translation.traces.trace import (
    TranslationTrace,
)

_RUNTIME_NAMESPACE = uuid.UUID("e4ed8a1a-13be-4ac1-bd19-1a2dbe506004")


class TranslationEgressRuntime:
    """Canonical-English → customer-language egress runtime."""

    def __init__(
        self,
        *,
        provider: BaseTranslationProvider,
        persistence: TranslationPersistenceProtocol,
        normalizer: BoundaryNormalizer | None = None,
        validator: SemanticPreservationValidator | None = None,
        runtime_instance_id: uuid.UUID | None = None,
        capability_governance: GovernanceRuntime,
    ) -> None:
        if capability_governance is None:  # pyright: ignore[reportUnnecessaryComparison]
            raise TranslationConfigurationError(
                "TranslationEgressRuntime requires capability_governance. "
                "Translation egress is an external action and must be "
                "governed."
            )
        self._provider = provider
        self._persistence = persistence
        self._normalizer = normalizer or BoundaryNormalizer()
        self._validator = (
            validator or SemanticPreservationValidator()
        )
        self._runtime_instance_id = (
            runtime_instance_id
            or derive_runtime_id(
                namespace=_RUNTIME_NAMESPACE,
                tenant_id=None,
                seed_components=(
                    "translation_egress_runtime",
                    provider.name,
                ),
            )
        )
        self._sequence = 0
        # 2.75-\u03b1: capability legality gate.
        self._capability_governance = capability_governance

    @property
    def runtime_instance_id(self) -> uuid.UUID:
        return self._runtime_instance_id

    @property
    def persistence(self) -> TranslationPersistenceProtocol:
        return self._persistence

    async def localize(
        self, request: EgressLocalizeRequest
    ) -> TranslationEnvelope:
        kind = TranslationTraceKind.EGRESS_LOCALIZE
        started_at = datetime.now(UTC)
        monotonic = time.perf_counter()
        # P2-A: singular authority resolution.
        resolution = request_authority_resolution(request)
        # 2.75-\u03b1: capability legality gate.
        denial = await gate_or_deny(
            self._capability_governance,
            act=OperationalAct.BOUNDARY_TRANSLATION_EGRESS,
            authority=request.authority,
            resolution=resolution,
            actor="translation_egress_runtime",
        )
        if denial is not None:
            return self._fail(
                kind, started_at, monotonic, request, denial,
                resolution=resolution,
            )
        try:
            self._validate_request(request)

            normalised_text, normalisation = (
                self._normalizer.normalize(
                    request.canonical.text,
                    language=CANONICAL_LANGUAGE,
                )
            )
            normalised_canonical = TranslationPayload(
                text=normalised_text,
                language=CANONICAL_LANGUAGE,
                attributes=request.canonical.attributes,
            )

            provider_response = await self._provider.translate(
                TranslationProviderRequest(
                    source=normalised_canonical,
                    target_language=request.context.target_language,
                )
            )
            localised_payload = provider_response.translated
            if (
                localised_payload.language
                != request.context.target_language
            ):
                raise TranslationProviderError(
                    f"provider returned language "
                    f"{localised_payload.language!r}; expected "
                    f"{request.context.target_language!r}"
                )

            preservation = self._validator.validate(
                canonical_text=normalised_canonical.text,
                candidate_text=localised_payload.text,
            )
            findings = _build_findings(preservation)

            ended_at = datetime.now(UTC)
            localization = LocalizationMetadata(
                canonical_payload=normalised_canonical,
                localized_payload=localised_payload,
                provider_name=provider_response.provider_name,
                formality=request.context.formality,
                normalization=normalisation,
                preservation=preservation,
                localized_at=ended_at,
                attributes=dict(request.attributes),
            )
            validation = TranslationValidation(
                status=TranslationStatus.LOCALIZED,
                normalization=normalisation,
                preservation=preservation,
                findings=findings,
                validated_at=ended_at,
            )

            identity = self._build_identity(request, resolution=resolution)
            canonical_fp = text_fingerprint(
                normalised_canonical.text,
                language=CANONICAL_LANGUAGE,
            )
            boundary_fp = text_fingerprint(
                localised_payload.text,
                language=localised_payload.language,
            )
            lineage_entry = TranslationLineageEntry(
                sequence=await self._next_lineage_sequence(
                    identity.correlation_id
                ),
                direction=TranslationDirection.EGRESS,
                canonical_fingerprint=canonical_fp,
                boundary_fingerprint=boundary_fp,
                provider_name=provider_response.provider_name,
                seed=request.seed,
            )
            replay = TranslationReplay(
                replay_id=derive_replay_id(seed=request.seed),
                seed=request.seed,
                canonical_fingerprint=canonical_fp,
                boundary_fingerprint=boundary_fp,
                provider_name=provider_response.provider_name,
                captured_at=ended_at,
            )

            record = EgressLocalizationRecord(
                identity=identity,
                localization=localization,
                validation=validation,
                lineage_entry=lineage_entry,
                replay=replay,
            )
            await self._persistence.write_egress(record)

            result = EgressLocalizeResult(
                sequence=self._next_sequence(),
                runtime_instance_id=self._runtime_instance_id,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                status=TranslationStatus.COMPLETED,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                metadata=dict(request.attributes),
                identity=identity,
                localization=localization,
                validation=validation,
                replay=replay,
            )
            return self._envelope(
                kind,
                started_at,
                ended_at,
                monotonic,
                request,
                result,
                provider_name=provider_response.provider_name,
                error=None,
                resolution=resolution,
            )
        except TranslationError as exc:
            return self._fail(
                kind, started_at, monotonic, request, exc,
                resolution=resolution,
            )

    # ── helpers ─────────────────────────────────────────────────────

    def _validate_request(
        self, request: EgressLocalizeRequest
    ) -> None:
        if request.canonical.language != CANONICAL_LANGUAGE:
            raise TranslationValidationError(
                f"egress canonical payload must be in "
                f"{CANONICAL_LANGUAGE!r}; got "
                f"{request.canonical.language!r}"
            )
        if request.canonical.attributes.get(
            "operational_directive"
        ):
            raise TranslationContainmentError(
                "egress translation MUST NEVER alter operational "
                "directives — caller passed "
                "'operational_directive' attribute."
            )

    def _build_identity(
        self,
        request: EgressLocalizeRequest,
        *,
        resolution: AuthorityResolution,
    ) -> TranslationIdentity:
        translation_id = derive_translation_id(
            seed=f"egress|{request.seed}"
        )
        lineage_id = derive_lineage_id(
            seed=f"lineage|{request.correlation_id or request.seed}"
        )
        correlation_id = derive_correlation_id(
            seed=request.correlation_id or request.seed
        )
        return TranslationIdentity(
            translation_id=translation_id,
            lineage_id=lineage_id,
            correlation_id=correlation_id,
            seed=request.seed,
            request_id=request.request_id,
            tenant_id=resolution.tenant_id,
        )

    async def _next_lineage_sequence(
        self, correlation_id: TranslationCorrelationId
    ) -> int:
        existing = (
            await self._persistence.list_lineage_entries(
                correlation_id
            )
        )
        return (
            existing[-1].sequence + 1 if existing else 0
        )

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _envelope(
        self,
        kind: TranslationTraceKind,
        started_at: datetime,
        ended_at: datetime,
        monotonic: float,
        request: EgressLocalizeRequest,
        result: EgressLocalizeResult,
        *,
        provider_name: str | None,
        error: BaseException | None,
        resolution: AuthorityResolution,
    ) -> TranslationEnvelope:
        sequence = self._sequence
        if request.correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{request.correlation_id}|"
                    f"{request.request_id}|"
                    f"{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        return TranslationEnvelope(
            trace=TranslationTrace(
                trace_id=trace_id,
                kind=kind,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                seed=request.seed,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                provider_name=provider_name,
                error=type(error).__name__ if error else None,
                tenant_authority_source=resolution.source.value,
            ),
            result=result,
            error=error,
        )

    def _fail(
        self,
        kind: TranslationTraceKind,
        started_at: datetime,
        monotonic: float,
        request: EgressLocalizeRequest,
        error: BaseException,
        *,
        resolution: AuthorityResolution,
    ) -> TranslationEnvelope:
        ended_at = datetime.now(UTC)
        sequence = self._next_sequence()
        if request.correlation_id:
            trace_id = derive_trace_id(
                seed=(
                    f"{kind.value}|{request.correlation_id}|"
                    f"err|{self._runtime_instance_id}|{sequence}"
                )
            )
        else:
            trace_id = generate_trace_id()
        return TranslationEnvelope(
            trace=TranslationTrace(
                trace_id=trace_id,
                kind=kind,
                runtime_instance_id=self._runtime_instance_id,
                sequence=sequence,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=(time.perf_counter() - monotonic)
                * 1000.0,
                seed=request.seed,
                correlation_id=request.correlation_id,
                request_id=request.request_id,
                tenant_id=resolution.tenant_id,
                error=type(error).__name__,
                tenant_authority_source=resolution.source.value,
            ),
            result=None,
            error=error,
        )


def _build_findings(
    preservation: SemanticPreservationCheck,
) -> tuple[TranslationFinding, ...]:
    out: list[TranslationFinding] = []
    ordinal = 0
    if preservation.canonical_tokens_missing:
        out.append(
            TranslationFinding(
                ordinal=ordinal,
                kind=TranslationFindingKind.PROHIBITED_TOKEN_LOSS,
                summary=(
                    f"governance tokens lost in localisation: "
                    f"{list(preservation.canonical_tokens_missing)}"
                ),
                evidence=tuple(
                    preservation.canonical_tokens_missing
                ),
            )
        )
        ordinal += 1
    if preservation.introduced_governance_tokens:
        out.append(
            TranslationFinding(
                ordinal=ordinal,
                kind=TranslationFindingKind.PROHIBITED_TOKEN_INJECTED,
                summary=(
                    f"governance tokens injected by localisation: "
                    f"{list(preservation.introduced_governance_tokens)}"
                ),
                evidence=tuple(
                    preservation.introduced_governance_tokens
                ),
            )
        )
        ordinal += 1
    return tuple(out)


__all__ = ["TranslationEgressRuntime"]
