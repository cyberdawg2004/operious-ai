"""Governance subsystem composition root.

Builds and exposes the governance runtime + the governed assembly
runtime, plus FastAPI providers for each.

Lifecycle:

* All registries / runtimes are constructed lazily via `lru_cache` and
  cached for the process lifetime.
* `GovernedAssemblyRuntime` instances are constructed per request and
  per orchestration-task registration — mirroring the
  `ContextAssemblyService` lifecycle from `app/dependencies/rag.py`.

Adding a new policy:
    1. Implement `BaseGovernancePolicy`.
    2. Register it in `_build_policy_registry()`.
    3. Add the policy name to the appropriate chain in
       `_build_chains()`.

Adding a new enforcement handler:
    1. Implement `BaseEnforcementHandler`.
    2. Register it in `_build_handler_registry()`. The registry's
       `assert_complete()` enforces one handler per `Decision`.

Adding a new enforcement stage to operational integration:
    Sprint I ships PRE_RETRIEVAL + PRE_EXECUTION wiring for context
    assembly only. POST_RETRIEVAL and PRE_GROUNDING wiring land when
    the assembly service exposes per-stage hooks — at that point this
    file gains chain entries for those stages.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, get_settings
from app._deprecated.dependencies.rag import (
    build_context_assembly_service_process_wide,
    get_context_assembly_service,
)
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
from app.governance.enums import EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app._deprecated.governance_bridge.guardrails.adapters import GovernedAssemblyRuntime
from app.governance.policies.builtin import (
    ContentDenylistPolicy,
    MaxQueryLengthPolicy,
    TenantScopePolicy,
)
from app.governance.policies.chain import PolicyChain
from app.governance.policies.registry import PolicyRegistry
from app._deprecated.rag.assembly.service import ContextAssemblyService


# ─── Policy registry ──────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_policy_registry() -> PolicyRegistry:
    settings = get_settings()
    registry = PolicyRegistry()
    registry.register(
        TenantScopePolicy(
            allowed_tenants=_csv_to_frozenset(settings.GOVERNANCE_TENANT_ALLOWLIST),
        )
    )
    registry.register(
        MaxQueryLengthPolicy(max_length=settings.GOVERNANCE_MAX_QUERY_LENGTH)
    )
    registry.register(
        ContentDenylistPolicy(
            denylist=_csv_to_tuple(settings.GOVERNANCE_CONTENT_DENYLIST),
        )
    )
    return registry


def get_policy_registry() -> PolicyRegistry:
    return _build_policy_registry()


# ─── Handler registry ─────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_handler_registry() -> EnforcementHandlerRegistry:
    registry = EnforcementHandlerRegistry()
    registry.register(AllowHandler())
    registry.register(DenyHandler())
    registry.register(RedactHandler())
    registry.register(DegradeHandler())
    registry.register(EscalateHandler())
    registry.register(RequireApprovalHandler())
    registry.assert_complete()
    return registry


def get_handler_registry() -> EnforcementHandlerRegistry:
    return _build_handler_registry()


# ─── Chain composition ────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_chains() -> dict[EnforcementStage, PolicyChain]:
    """Wire concrete policy chains for the stages we integrate today.

    Sprint I ships PRE_RETRIEVAL + PRE_EXECUTION integration via
    `GovernedAssemblyRuntime`. POST_RETRIEVAL, PRE_GROUNDING,
    POST_EXECUTION are first-class enum values; their chains land when
    operational integrations are added in future sprints.
    """
    registry = _build_policy_registry()
    return {
        EnforcementStage.PRE_RETRIEVAL: PolicyChain.from_registry(
            chain_id="pre_retrieval.default",
            stage=EnforcementStage.PRE_RETRIEVAL,
            policy_names=("tenant_scope", "max_query_length"),
            registry=registry,
        ),
        EnforcementStage.PRE_EXECUTION: PolicyChain.from_registry(
            chain_id="pre_execution.default",
            stage=EnforcementStage.PRE_EXECUTION,
            policy_names=("tenant_scope",),
            registry=registry,
        ),
    }


# ─── Governance runtime ───────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_governance_runtime() -> GovernanceRuntime:
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_build_handler_registry(),
        chains=_build_chains(),
    )


def get_governance_runtime() -> GovernanceRuntime:
    return _build_governance_runtime()


# ─── Governed assembly runtime ────────────────────────────────────────


def get_governed_assembly_runtime(
    assembly_service: ContextAssemblyService = Depends(get_context_assembly_service),
) -> GovernedAssemblyRuntime:
    """FastAPI dependency: per-request `GovernedAssemblyRuntime`."""
    return GovernedAssemblyRuntime(
        governance_runtime=_build_governance_runtime(),
        assembly_service=assembly_service,
    )


def build_governed_assembly_runtime_process_wide() -> GovernedAssemblyRuntime:
    return GovernedAssemblyRuntime(
        governance_runtime=_build_governance_runtime(),
        assembly_service=build_context_assembly_service_process_wide(),
    )


# ─── Parsing helpers ──────────────────────────────────────────────────


def _csv_to_tuple(raw: str) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _csv_to_frozenset(raw: str) -> frozenset[str]:
    return frozenset(_csv_to_tuple(raw))


__all__ = [
    "get_policy_registry",
    "get_handler_registry",
    "get_governance_runtime",
    "get_governed_assembly_runtime",
    "build_governed_assembly_runtime_process_wide",
]
