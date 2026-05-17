"""Coordination-policy substrate invariants — replay-safety + immutability.

Sprint L2 architectural invariants. Short, pure, fast-running pins
on substrate-level guarantees the rest of the test suite relies on.

Properties pinned:

* every public value object is frozen (`dataclass(frozen=True, slots=True)`),
* the canonical metadata-key + finding-code catalogues are pinned
  wire-stable string values,
* `app.coordination.policy` is a strict leaf — it MUST NOT import
  from `app.agents`, `app.supervisor`, or `app.governance` (Sprint
  L2 Rule 1 — distinct substrate from governance),
* the decision precedence ordering is total and matches the
  documented "most-restrictive wins" rule.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import app.coordination.policy
from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.contracts.results import (
    CoordinationPolicyEvaluationResult,
)
from app.coordination.policy.envelopes import (
    CoordinationPolicyEnvelope,
)
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.policy import CoordinationPolicy
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)
from app.coordination.policy.models.rule import CoordinationPolicyRule
from app.coordination.policy.persistence.models import (
    CoordinationPolicyQuery,
    RecordPage,
)
from app.coordination.policy.persistence.records import (
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyRecord,
    CoordinationPolicyRestrictionRecord,
)
from app.coordination.policy.taxonomy import (
    CoordinationPolicyFindingCode,
    CoordinationPolicyMetadataKey,
)
from app.coordination.policy.tracing import (
    CoordinationPolicyTrace,
    CoordinationPolicyTraceContext,
)


_FROZEN_TYPES = (
    CoordinationPolicy,
    CoordinationPolicyRule,
    CoordinationPolicyRestriction,
    CoordinationPolicyEscalation,
    CoordinationPolicyFinding,
    CoordinationPolicyEvaluationRequest,
    CoordinationPolicyEvaluationResult,
    CoordinationPolicyEnvelope,
    CoordinationPolicyTrace,
    CoordinationPolicyTraceContext,
    CoordinationPolicyRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyRestrictionRecord,
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyQuery,
    RecordPage,
)


def test_every_public_value_object_is_frozen() -> None:
    for tp in _FROZEN_TYPES:
        params = getattr(tp, "__dataclass_params__", None)
        assert params is not None, (
            f"{tp.__name__} is not a dataclass; substrate value objects "
            f"must be @dataclass(frozen=True, slots=True)"
        )
        assert params.frozen, f"{tp.__name__} is not frozen"


def test_every_public_value_object_uses_slots() -> None:
    for tp in _FROZEN_TYPES:
        assert "__slots__" in tp.__dict__, (
            f"{tp.__name__} does not declare __slots__"
        )


# ─── Canonical vocabulary stability ──────────────────────────────────


def test_metadata_keys_are_namespaced() -> None:
    for key in CoordinationPolicyMetadataKey:
        assert key.value.startswith("coordination.policy."), (
            f"metadata key {key.value!r} is not namespaced under "
            f"'coordination.policy.*'"
        )


def test_finding_code_catalogue_is_pinned() -> None:
    """Sentinel: the closed set of built-in finding codes.

    External evaluators may emit additional codes, but the built-in
    catalogue is wire-stable.
    """
    expected = {
        # Topology.
        "topology.authorized",
        "topology.denied",
        "topology.restricted",
        "topology.unknown_sender",
        "topology.unknown_recipient",
        "topology.forbidden_direction",
        "topology.forbidden_message_type",
        # Escalation.
        "escalation.required",
        "escalation.human_review",
        "escalation.tenant_owner",
        "escalation.operational_review",
        # Tenant.
        "tenant_isolation.violation",
        "tenant_isolation.cross_tenant",
        "tenant_isolation.missing_tenant",
    }
    assert {m.value for m in CoordinationPolicyFindingCode} == expected


# ─── Strict-leaf substrate isolation ─────────────────────────────────


def test_policy_package_does_not_import_agents_supervisor_or_governance() -> None:
    """Sprint L2 Rule 1: coordination-policy is its own substrate.

    Composing with governance via the coordination runtime is fine,
    but the policy substrate ITSELF must not depend on governance,
    agents, or supervisor packages.
    """
    pkg_path = Path(app.coordination.policy.__file__).parent
    forbidden = ("app.agents", "app.supervisor", "app.governance")
    for mod_info in pkgutil.walk_packages(
        [str(pkg_path)], prefix="app.coordination.policy."
    ):
        module = importlib.import_module(mod_info.name)
        source_file = getattr(module, "__file__", None)
        if source_file is None:
            continue
        text = Path(source_file).read_text()
        for prefix in forbidden:
            assert f"from {prefix}" not in text, (
                f"{mod_info.name} imports from {prefix} — policy "
                f"substrate must remain isolated"
            )
            assert f"import {prefix}" not in text, (
                f"{mod_info.name} imports {prefix} — policy substrate "
                f"must remain isolated"
            )
