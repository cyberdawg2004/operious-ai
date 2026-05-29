"""Redis-activated crisis governance policies."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, FrozenSet, Sequence, cast

import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision, PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.registry import PolicyRegistry
from app.governance.subjects.agent_actions import AgentActionGovernanceSubject
from app.governance.subjects.base import GenericGovernanceSubject, SubjectKind
from app.governance.subjects.execution import ExecutionGovernanceSubject

CRISIS_KEY_PREFIX = "crisis"
_SKU_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}")
_logger = get_logger(__name__)


def _crisis_key(tenant_id: str, template: str, scope: str = "") -> str:
    if scope:
        return f"{CRISIS_KEY_PREFIX}:{tenant_id}:{template}:{scope}"
    return f"{CRISIS_KEY_PREFIX}:{tenant_id}:{template}"


class _BaseCrisisPolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )

    def __init__(self, *, redis: aioredis.Redis) -> None:
        self._redis = redis

    async def _get_activation(self, key: str) -> str | None:
        try:
            value = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001 - crisis rules fail open.
            _logger.warning(
                "crisis_policy_redis_read_failed",
                extra={
                    "policy_name": self.name,
                    "redis_key": key,
                    "error": str(exc),
                },
            )
            return None
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    def _allow(self, *, rule_id: str = "crisis_dormant", reason: str) -> tuple[PolicyEvaluationResult, ...]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id=rule_id,
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason=reason,
                metadata={"crisis_policy": self.name, "active": False},
            ),
        )

    def _crisis_result(
        self,
        *,
        rule_id: str,
        decision: Decision,
        severity: ViolationSeverity,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[PolicyEvaluationResult, ...]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id=rule_id,
                decision=decision,
                severity=severity,
                reason=reason,
                metadata={
                    "crisis_policy": self.name,
                    "active": True,
                    **dict(metadata or {}),
                },
            ),
        )


class CrisisBlockSKUPolicy(_BaseCrisisPolicy):
    """DENY diagnostic executions when an activated SKU appears in the subject."""

    name: ClassVar[str] = "crisis.block_sku"
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.EXECUTION, SubjectKind.GENERIC}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        tenant_id = _tenant_id_for(context)
        if tenant_id is None:
            return self._allow(reason="crisis:block_sku dormant; tenant unavailable")
        text = _subject_text(context)
        for sku in _sku_candidates(text):
            key = _crisis_key(tenant_id, "block_sku", sku)
            if await self._get_activation(key) is None:
                continue
            return self._crisis_result(
                rule_id="crisis_block_sku",
                decision=Decision.DENY,
                severity=ViolationSeverity.CRITICAL,
                reason=f"crisis:block_sku denied ticket mentioning SKU {sku}",
                metadata={"template": "block_sku", "sku": sku, "redis_key": key},
            )
        return self._allow(reason="crisis:block_sku dormant")


class CrisisHaltRefundsPolicy(_BaseCrisisPolicy):
    """REQUIRE_APPROVAL for refund actions while the tenant halt is active."""

    name: ClassVar[str] = "crisis.halt_refunds"
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION, SubjectKind.EXECUTION, SubjectKind.GENERIC}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        tenant_id = _tenant_id_for(context)
        if tenant_id is None:
            return self._allow(reason="crisis:halt_refunds dormant; tenant unavailable")
        key = _crisis_key(tenant_id, "halt_refunds")
        if await self._get_activation(key) is None:
            return self._allow(reason="crisis:halt_refunds dormant")
        if not _subject_mentions_refund_action(context):
            return self._allow(
                rule_id="crisis_active_subject_not_refund",
                reason="crisis:halt_refunds active but subject is not a refund action",
            )
        return self._crisis_result(
            rule_id="crisis_halt_refunds",
            decision=Decision.REQUIRE_APPROVAL,
            severity=ViolationSeverity.CRITICAL,
            reason="crisis:halt_refunds requires approval for refund action",
            metadata={"template": "halt_refunds", "redis_key": key},
        )


class CrisisEscalateAllPolicy(_BaseCrisisPolicy):
    """ESCALATE every diagnostic or action execution while active."""

    name: ClassVar[str] = "crisis.escalate_all"
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.EXECUTION, SubjectKind.AGENT_ACTION, SubjectKind.GENERIC}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        tenant_id = _tenant_id_for(context)
        if tenant_id is None:
            return self._allow(reason="crisis:escalate_all dormant; tenant unavailable")
        key = _crisis_key(tenant_id, "escalate_all")
        if await self._get_activation(key) is None:
            return self._allow(reason="crisis:escalate_all dormant")
        return self._crisis_result(
            rule_id="crisis_escalate_all",
            decision=Decision.ESCALATE,
            severity=ViolationSeverity.CRITICAL,
            reason="crisis:escalate_all escalated tenant execution",
            metadata={"template": "escalate_all", "redis_key": key},
        )


class CrisisFreezeCategoryPolicy(_BaseCrisisPolicy):
    """DENY diagnostic executions matching an activated category freeze."""

    name: ClassVar[str] = "crisis.freeze_category"
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.EXECUTION, SubjectKind.GENERIC}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        tenant_id = _tenant_id_for(context)
        category = _subject_category(context)
        if tenant_id is None or category is None:
            return self._allow(
                reason="crisis:freeze_category dormant; tenant or category unavailable"
            )
        key = _crisis_key(tenant_id, "freeze_category", category)
        if await self._get_activation(key) is None:
            return self._allow(reason="crisis:freeze_category dormant")
        return self._crisis_result(
            rule_id="crisis_freeze_category",
            decision=Decision.DENY,
            severity=ViolationSeverity.CRITICAL,
            reason=f"crisis:freeze_category denied category {category}",
            metadata={
                "template": "freeze_category",
                "category": category,
                "redis_key": key,
            },
        )


def build_crisis_policies(
    *,
    redis: aioredis.Redis | None,
) -> tuple[BaseGovernancePolicy, ...]:
    if redis is None:
        return ()
    return (
        CrisisBlockSKUPolicy(redis=redis),
        CrisisHaltRefundsPolicy(redis=redis),
        CrisisEscalateAllPolicy(redis=redis),
        CrisisFreezeCategoryPolicy(redis=redis),
    )


def build_crisis_policy_registry(
    *,
    redis: aioredis.Redis,
) -> PolicyRegistry:
    registry = PolicyRegistry()
    for policy in build_crisis_policies(redis=redis):
        registry.register(policy)
    return registry


def crisis_policy_name_from_decision(decision: GovernanceDecision) -> str | None:
    for result in decision.evaluated_rules:
        if (
            result.decision is not Decision.ALLOW
            and result.policy_name.startswith("crisis.")
        ):
            return result.policy_name
    return None


def _tenant_id_for(context: GovernanceContext) -> str | None:
    subject_tenant = getattr(context.subject, "tenant_id", None)
    if subject_tenant is not None:
        return str(subject_tenant)
    if context.tenant_id is not None:
        return str(context.tenant_id)
    return None


def _subject_text(context: GovernanceContext) -> str:
    subject = context.subject
    fragments: list[str] = []
    if isinstance(subject, ExecutionGovernanceSubject):
        fragments.append(subject.query)
    if isinstance(subject, GenericGovernanceSubject):
        fragments.extend(_string_fragments(subject.data))
    fragments.extend(_string_fragments(subject.metadata))
    fragments.extend(_string_fragments(context.metadata))
    return " ".join(part for part in fragments if part)


def _subject_category(context: GovernanceContext) -> str | None:
    subject = context.subject
    for value in (
        getattr(subject, "category", None),
        subject.metadata.get("category"),
        subject.metadata.get("issue_category"),
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    if isinstance(subject, GenericGovernanceSubject):
        data_value = subject.data.get("category")
        if isinstance(data_value, str) and data_value.strip():
            return data_value.strip()
    return None


def _subject_mentions_refund_action(context: GovernanceContext) -> bool:
    subject = context.subject
    haystack: list[str] = [context.action, context.resource]
    if isinstance(subject, AgentActionGovernanceSubject):
        haystack.extend(
            [
                subject.capability,
                subject.tool_name or "",
                subject.target_resource,
                subject.execution_scope,
            ]
        )
    if isinstance(subject, ExecutionGovernanceSubject):
        haystack.append(subject.execution_action)
    haystack.extend(_string_fragments(subject.metadata))
    return "refund" in " ".join(haystack).lower()


def _sku_candidates(text: str) -> tuple[str, ...]:
    candidates: list[str] = []
    seen: set[str] = set()
    for match in _SKU_TOKEN_RE.finditer(text):
        token = match.group(0).strip()
        for candidate in (token, token.upper(), token.lower()):
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
                if len(candidates) >= 64:
                    return tuple(candidates)
    return tuple(candidates)


def _string_fragments(value: object) -> Iterable[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            yield stripped
        return
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        for nested in mapping.values():
            yield from _string_fragments(nested)
        return
    if isinstance(value, list | tuple | set | frozenset):
        iterable = cast(Iterable[object], value)
        for nested in iterable:
            yield from _string_fragments(nested)


__all__ = [
    "CRISIS_KEY_PREFIX",
    "CrisisBlockSKUPolicy",
    "CrisisEscalateAllPolicy",
    "CrisisFreezeCategoryPolicy",
    "CrisisHaltRefundsPolicy",
    "_crisis_key",
    "build_crisis_policy_registry",
    "build_crisis_policies",
    "crisis_policy_name_from_decision",
]
