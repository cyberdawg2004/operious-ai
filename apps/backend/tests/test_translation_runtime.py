"""End-to-end tests for the translation runtime."""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import pytest

from app.boundary.translation import (
    EgressLocalizeRequest,
    EgressLocalizeResult,
    InMemoryTranslationPersistence,
    IdentityTranslationProvider,
    IngressTranslateResult,
    IngressTranslateRequest,
    LocalizationContext,
    LocalizationFormality,
    TranslationConfigurationError,
    TranslationContainmentError,
    TranslationDirection,
    TranslationEgressRuntime,
    TranslationIngressRuntime,
    TranslationPayload,
    TranslationRuntime,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.subjects.base import SubjectKind


class _AllowCapabilityPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "translation_runtime_allow_capability"
    supported_stages: ClassVar[frozenset[EnforcementStage]] = (
        frozenset({EnforcementStage.PRE_REQUEST})
    )
    applicable_subject_kinds: ClassVar[frozenset[SubjectKind]] = (
        frozenset({SubjectKind.CAPABILITY})
    )

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="translation_runtime_allowed",
                decision=Decision.ALLOW,
                reason="translation runtime fixture allows capability gate",
            ),
        )


def _handlers() -> EnforcementHandlerRegistry:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return registry


def _allowing_governance() -> GovernanceRuntime:
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handlers(),
        chains={
            EnforcementStage.PRE_REQUEST: PolicyChain(
                chain_id="translation-runtime-test-capability",
                stage=EnforcementStage.PRE_REQUEST,
                policies=(_AllowCapabilityPolicy(),),
            )
        },
        persistence=InMemoryGovernanceRepository(),
    )


@pytest.fixture()
def runtime() -> TranslationRuntime:
    persistence = InMemoryTranslationPersistence()
    provider = IdentityTranslationProvider()
    return TranslationRuntime(
        ingress=TranslationIngressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=_allowing_governance(),
        ),
        egress=TranslationEgressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=_allowing_governance(),
        ),
    )


def test_translation_egress_requires_governance_at_construction() -> None:
    persistence = InMemoryTranslationPersistence()
    provider = IdentityTranslationProvider()

    with pytest.raises(TranslationConfigurationError):
        TranslationEgressRuntime(
            provider=provider,
            persistence=persistence,
            capability_governance=None,
        )


@pytest.mark.asyncio
async def test_ingress_translate_returns_canonical_envelope(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="Por favor escalate", language="es"
            ),
            seed="i1",
            correlation_id="conv-1",
        )
    )
    assert env.is_ok
    assert isinstance(env.result, IngressTranslateResult)
    assert env.result.projection is not None
    assert env.result.projection.canonical_payload.language == "en"
    assert env.result.replay is not None


@pytest.mark.asyncio
async def test_ingress_rejects_operational_directive(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="x",
                language="es",
                attributes={"operational_directive": True},
            ),
            seed="i2",
        )
    )
    assert env.error is not None
    assert isinstance(env.error, TranslationContainmentError)


@pytest.mark.asyncio
async def test_egress_localize_persists_lineage(
    runtime: TranslationRuntime,
) -> None:
    await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="hola", language="es"
            ),
            seed="i3",
            correlation_id="conv-2",
        )
    )
    env = await runtime.egress.localize(
        EgressLocalizeRequest(
            canonical=TranslationPayload(
                text="The team will respond.",
                language="en",
            ),
            context=LocalizationContext(
                target_language="es",
                formality=LocalizationFormality.NEUTRAL,
            ),
            seed="e1",
            correlation_id="conv-2",
        )
    )
    assert env.is_ok
    assert isinstance(env.result, EgressLocalizeResult)
    assert env.result.identity is not None
    lineage = await runtime.persistence.reconstruct_lineage(
        env.result.identity.correlation_id
    )
    assert lineage is not None
    assert [e.direction for e in lineage.entries] == [
        TranslationDirection.INGRESS,
        TranslationDirection.EGRESS,
    ]


@pytest.mark.asyncio
async def test_egress_rejects_non_canonical_input(
    runtime: TranslationRuntime,
) -> None:
    env = await runtime.egress.localize(
        EgressLocalizeRequest(
            canonical=TranslationPayload(
                text="hola", language="es"
            ),
            context=LocalizationContext(
                target_language="es",
                formality=LocalizationFormality.NEUTRAL,
            ),
            seed="e-bad",
        )
    )
    assert env.error is not None


@pytest.mark.asyncio
async def test_replay_records_are_byte_stable(
    runtime: TranslationRuntime,
) -> None:
    a = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="hola", language="es"
            ),
            seed="r1",
            correlation_id="conv-r",
        )
    )
    b = await runtime.ingress.translate(
        IngressTranslateRequest(
            source=TranslationPayload(
                text="adios", language="es"
            ),
            seed="r2",
            correlation_id="conv-r2",
        )
    )
    assert isinstance(a.result, IngressTranslateResult)
    assert isinstance(b.result, IngressTranslateResult)
    assert a.result.replay is not None
    assert b.result.replay is not None
    assert (
        a.result.replay.canonical_fingerprint
        != b.result.replay.canonical_fingerprint
    )
