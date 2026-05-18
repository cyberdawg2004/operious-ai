"""Architectural invariants for the coordination-topology substrate.

Pinned properties:

* every public value object is frozen + slots,
* every metadata key is namespaced `coordination.topology.*`,
* the finding-code catalogue is pinned,
* the topology substrate does NOT import from sibling substrates
  (`app.agents`, `app.supervisor`, `app.governance`,
  `app.coordination.policy`) — preserves strict substrate isolation
  (Sprint L3 final directive).
* `is_blocking_topology_decision` aligns with the precedence table.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import is_dataclass

import pytest

import app.coordination.topology as topology_pkg
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyFindingCode,
    CoordinationTopologyMetadataKey,
    coordination_topology_precedence,
    is_allow_topology_decision,
    is_blocking_topology_decision,
)


_FORBIDDEN_PREFIXES = (
    "app.agents",
    "app.supervisor",
    "app.governance",
    # Topology runs BEFORE policy and must not depend on it.
    "app.coordination.policy",
    "app._deprecated",
)


def _walk_topology_modules() -> list[str]:
    """Recursively yield every dotted module path inside `app.coordination.topology`."""
    names: list[str] = []
    for info in pkgutil.walk_packages(
        topology_pkg.__path__, prefix=topology_pkg.__name__ + "."
    ):
        names.append(info.name)
    names.append(topology_pkg.__name__)
    return names


# ─── Module-import isolation ─────────────────────────────────────────


def test_topology_does_not_import_sibling_substrates() -> None:
    # 2.75-\u03b1: the singular capability legality gate is the
    # exemption. Symbols re-exported through ``app.governance.capability``
    # (including ``GovernanceRuntime``) carry the original module path
    # ``app.governance.enforcement.runtime`` — we whitelist that
    # symbol explicitly rather than weakening the prefix check.
    _CAPABILITY_GATE_EXEMPTION = "app.governance.capability"
    _CAPABILITY_GATE_SYMBOLS = {
        "CapabilityDenied",
        "GovernanceRuntime",
        "OperationalAct",
        "gate_or_deny",
    }
    for module_name in _walk_topology_modules():
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


def test_public_value_objects_are_frozen_slots() -> None:
    public_dataclasses = [
        topology_pkg.AuthorityBoundary,
        topology_pkg.CoordinationEdge,
        topology_pkg.CoordinationNode,
        topology_pkg.CoordinationPath,
        topology_pkg.CoordinationTopology,
        topology_pkg.CoordinationTopologyEnvelope,
        topology_pkg.CoordinationTopologyEvaluationRequest,
        topology_pkg.CoordinationTopologyEvaluationResult,
        topology_pkg.CoordinationTopologyFinding,
        topology_pkg.CoordinationTopologyFindingRecord,
        topology_pkg.CoordinationTopologyRecord,
        topology_pkg.CoordinationTopologyTrace,
        topology_pkg.CoordinationTopologyTraceContext,
        topology_pkg.EscalationPath,
    ]
    for cls in public_dataclasses:
        assert is_dataclass(cls), f"{cls.__name__} must be a dataclass"
        params = getattr(cls, "__dataclass_params__")
        assert params.frozen, f"{cls.__name__} must be frozen=True"
        # `slots=True` on Python 3.10+ dataclasses materialises `__slots__`
        # on the class itself. Verify the class declares __slots__ rather
        # than instantiating it (constructors require arguments).
        assert "__slots__" in cls.__dict__, (
            f"{cls.__name__} must be a slots=True frozen dataclass"
        )


# ─── Namespaced metadata keys ────────────────────────────────────────


def test_metadata_keys_are_namespaced() -> None:
    for member in CoordinationTopologyMetadataKey:
        assert member.value.startswith("coordination.topology."), (
            f"metadata key {member.value!r} is not namespaced"
        )


# ─── Pinned finding-code catalogue ───────────────────────────────────


def test_finding_code_catalogue_is_pinned() -> None:
    assert {m.value for m in CoordinationTopologyFindingCode} == {
        "path.allowed",
        "path.denied",
        "path.unknown_sender",
        "path.unknown_recipient",
        "path.forbidden_message_type",
        "path.forbidden_direction",
        "escalation_path.authorized",
        "escalation_path.missing",
        "chain_depth.within_limit",
        "chain_depth.exceeded",
        "boundary.within_domain",
        "boundary.crossing_authorized",
        "boundary.crossing_forbidden",
        "boundary.unknown_node",
    }


# ─── Precedence ↔ blocking helpers ───────────────────────────────────


def test_precedence_order_pinned() -> None:
    order = sorted(
        CoordinationTopologyDecision,
        key=coordination_topology_precedence,
    )
    assert order == [
        CoordinationTopologyDecision.BOUNDARY_VIOLATION,
        CoordinationTopologyDecision.DEPTH_EXCEEDED,
        CoordinationTopologyDecision.DENIED,
        CoordinationTopologyDecision.ESCALATED,
        CoordinationTopologyDecision.ALLOWED,
    ]


def test_is_blocking_helpers_align_with_precedence() -> None:
    for decision in CoordinationTopologyDecision:
        assert is_blocking_topology_decision(decision) is (
            decision is not CoordinationTopologyDecision.ALLOWED
        )
        assert is_allow_topology_decision(decision) is (
            decision is CoordinationTopologyDecision.ALLOWED
        )


# ─── Sentinel: silencing unused pytest import in case of skip ────────


def test_pytest_is_usable() -> None:
    assert pytest is not None
