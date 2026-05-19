"""Architectural invariants for the arbitration substrate.

Pinned properties:

* every public value object is frozen + slots,
* every metadata key is namespaced ``arbitration.*``,
* the finding-code catalogue is pinned,
* the arbitration substrate does NOT import from sibling
  substrates (governance / topology / policy / coordination /
  supervisor / agents / memory / embeddings / replay / tracing
  modules),
* the runtime exposes NO execution surface (no `dispatch`,
  `execute`, `retry`, `invoke_tool`, …),
* the authority hierarchy is the canonical pinned order.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from dataclasses import fields, is_dataclass

import pytest

import app.arbitration as arbitration_pkg
from app.arbitration.enums import ArbitrationAuthorityLevel
from app.arbitration.runtime.runtime import (
    OperationalArbitrationRuntime,
)
from app.arbitration.taxonomy import (
    ArbitrationFindingCode,
    ArbitrationMetadataKey,
    arbitration_authority_precedence,
)


_FORBIDDEN_PREFIXES = (
    "app.agents",
    "app.supervisor",
    "app.governance",
    "app.coordination",  # sibling — arbitration is NOT inlined here
    "app.memory",
    "app.embeddings",
    "app.replay",
    "app.tracing",
    "app.db",
    "app.providers",
    "app._deprecated",
)


def _walk_arbitration_modules() -> list[str]:
    """Recursively yield every dotted module path inside ``app.arbitration``."""
    names: list[str] = []
    for info in pkgutil.walk_packages(
        arbitration_pkg.__path__,
        prefix=arbitration_pkg.__name__ + ".",
    ):
        names.append(info.name)
    names.append(arbitration_pkg.__name__)
    return names


# ─── Module-import isolation ─────────────────────────────────────────


def test_arbitration_does_not_import_sibling_substrates() -> None:
    # 2.75-\u03b1: the singular capability legality gate is the ONLY
    # cross-substrate surface arbitration is permitted to consume.
    # The gate re-exports ``GovernanceRuntime`` so leaf substrates
    # can take the runtime type as a constructor parameter without
    # naming ``app.governance.enforcement.*`` directly. The symbol
    # whitelist below pins the only cross-substrate names allowed
    # to leak into arbitration's module namespace.
    _CAPABILITY_GATE_EXEMPTION = "app.governance.capability"
    _CAPABILITY_GATE_SYMBOLS = {
        "CapabilityDenied",
        "GovernanceRuntime",
        "OperationalAct",
        "gate_or_deny",
    }
    for module_name in _walk_arbitration_modules():
        module = importlib.import_module(module_name)
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            obj_module = getattr(obj, "__module__", None)
            if not isinstance(obj_module, str):
                continue
            if obj_module.startswith(_CAPABILITY_GATE_EXEMPTION):
                continue
            if attr_name in _CAPABILITY_GATE_SYMBOLS:
                continue
            for forbidden in _FORBIDDEN_PREFIXES:
                assert not obj_module.startswith(forbidden), (
                    f"{module_name} imported {attr_name!r} from "
                    f"forbidden module {obj_module!r}"
                )


# ─── Frozen + slotted value objects ──────────────────────────────────


def test_public_value_objects_are_frozen_dataclasses() -> None:
    public_dataclasses = [
        arbitration_pkg.ArbitrationCase,
        arbitration_pkg.ArbitrationConflict,
        arbitration_pkg.ArbitrationDecision,
        arbitration_pkg.ArbitrationEnvelope,
        arbitration_pkg.ArbitrationFinding,
        arbitration_pkg.ArbitrationRecommendation,
        arbitration_pkg.ArbitrationRequest,
        arbitration_pkg.ArbitrationResult,
        arbitration_pkg.ArbitrationSignal,
        arbitration_pkg.ArbitrationTrace,
        arbitration_pkg.ArbitrationTraceContext,
        arbitration_pkg.ArbitrationConflictRecord,
        arbitration_pkg.ArbitrationDeadlockRecord,
        arbitration_pkg.ArbitrationFindingRecord,
        arbitration_pkg.ArbitrationRecord,
        arbitration_pkg.DeadlockWitness,
        arbitration_pkg.ResolutionAuthority,
    ]
    for cls in public_dataclasses:
        # Bind ``__name__`` before ``is_dataclass`` narrows ``cls`` to the
        # ``DataclassInstance`` protocol (which intentionally does not
        # expose class-level introspection attributes).
        cls_name = cls.__name__
        assert is_dataclass(cls), f"{cls_name} must be a dataclass"
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen, f"{cls_name} must be frozen=True"
        # The slots check: cls.__dict__ should declare __slots__.
        assert "__slots__" in cls.__dict__, (
            f"{cls_name} must declare __slots__"
        )
        # Sanity: fields are accessible.
        assert fields(cls) is not None


# ─── Namespaced metadata keys ────────────────────────────────────────


def test_metadata_keys_are_namespaced() -> None:
    for member in ArbitrationMetadataKey:
        assert member.value.startswith("arbitration."), (
            f"metadata key {member.value!r} is not namespaced"
        )


# ─── Pinned finding-code catalogue ───────────────────────────────────


def test_finding_code_catalogue_is_pinned() -> None:
    assert {m.value for m in ArbitrationFindingCode} == {
        "arbitration.authority_precedence_applied",
        "arbitration.resolution_inconclusive",
        "arbitration.no_conflict",
        "arbitration.insufficient_signals",
        "arbitration.contradictory_findings",
        "arbitration.conflicting_recommendations",
        "arbitration.escalation_conflict",
        "arbitration.supervisor_disagreement",
        "arbitration.authorisation_quality_cross",
        "arbitration.deadlock_detected",
        "arbitration.deadlock_risk",
    }


# ─── Authority hierarchy pinning ─────────────────────────────────────


def test_authority_hierarchy_is_canonical() -> None:
    order = sorted(
        ArbitrationAuthorityLevel,
        key=arbitration_authority_precedence,
    )
    assert order == [
        ArbitrationAuthorityLevel.GOVERNANCE,
        ArbitrationAuthorityLevel.TOPOLOGY,
        ArbitrationAuthorityLevel.POLICY,
        ArbitrationAuthorityLevel.ARBITRATION,
        ArbitrationAuthorityLevel.SUPERVISOR,
        ArbitrationAuthorityLevel.EXECUTION,
    ]


# ─── Runtime exposes ONLY interpretive surface ───────────────────────


def test_runtime_has_no_executive_methods() -> None:
    """The runtime must NOT expose execution-style methods.

    L4 architectural warning: arbitration is interpretive, not
    executive. No `dispatch`, `execute`, `retry`, `invoke_tool`,
    `mutate`, `replan`, `repair`, `schedule` on the runtime.
    """
    forbidden = {
        "dispatch",
        "execute",
        "retry",
        "invoke_tool",
        "invoke",
        "mutate",
        "replan",
        "repair",
        "schedule",
        "kick",
        "fanout",
        "trigger",
        "route",
        "reroute",
    }
    rt_members = {
        name
        for name, _ in inspect.getmembers(
            OperationalArbitrationRuntime
        )
        if not name.startswith("_")
    }
    leaked = rt_members & forbidden
    assert not leaked, (
        f"OperationalArbitrationRuntime exposes forbidden "
        f"executive surface: {leaked!r}"
    )
    # The substrate's sole public method is `evaluate`.
    assert "evaluate" in rt_members


def test_runtime_evaluate_is_async() -> None:
    assert inspect.iscoroutinefunction(
        OperationalArbitrationRuntime.evaluate
    )


# ─── Sentinel ────────────────────────────────────────────────────────


def test_pytest_is_usable() -> None:
    assert pytest is not None
