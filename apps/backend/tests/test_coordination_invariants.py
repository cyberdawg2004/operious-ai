"""Coordination substrate invariants — replay-safety + immutability.

Sprint L1 architectural invariant tests. These are short, pure,
fast-running pins on substrate-level guarantees the rest of the
test suite relies on.

Properties pinned:

* every public value object is frozen (`dataclass(frozen=True)`),
* `CoordinationEnvelope.is_delivered` derives correctly from status,
* the substrate is a strict leaf in the dependency graph — the
  coordination package MUST NOT import from `app/agents/` or
  `app/supervisor/` (Rule 1 + Rule 7),
* the canonical metadata-key + governance-action catalogues are
  pinned wire-stable string values,
* `CoordinationDispatchOutcome` set is pinned.
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
from pathlib import Path

import app.coordination
from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import CoordinationStatus
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.models import (
    CoordinationQuery,
    RecordPage,
)
from app.coordination.persistence.records import CoordinationRecord
from app.coordination.taxonomy import (
    CoordinationGovernanceAction,
    CoordinationMetadataKey,
)
from app.coordination.tracing import (
    CoordinationTrace,
    CoordinationTraceContext,
)


_FROZEN_TYPES = (
    CoordinationMessage,
    CoordinationDispatchRequest,
    CoordinationDispatchResult,
    CoordinationEnvelope,
    CoordinationParticipant,
    CoordinationPayload,
    CoordinationRecipient,
    CoordinationRecord,
    CoordinationQuery,
    RecordPage,
    CoordinationTrace,
    CoordinationTraceContext,
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
            f"{tp.__name__} does not declare __slots__; substrate value "
            f"objects must be slotted for replay-grade memory layout"
        )


def test_dispatch_outcome_set_is_pinned() -> None:
    assert {m.value for m in CoordinationDispatchOutcome} == {
        "accepted",
        "degraded",
        "denied",
        "policy_denied",
        "policy_escalated",
        "policy_error",
        "topology_denied",
        "topology_escalated",
        "topology_depth_exceeded",
        "topology_boundary_violation",
        "topology_error",
        "validation_error",
        "persistence_error",
        "governance_error",
    }


def test_envelope_is_delivered_derives_from_status() -> None:
    # Build a minimal envelope skeleton via dataclasses.replace —
    # avoiding the runtime's lock by constructing directly.
    from datetime import datetime, timezone
    import uuid
    from app.coordination.enums import (
        CoordinationDirection,
        CoordinationMessageType,
        CoordinationPriority,
    )
    from app.coordination.identity import (
        derive_coordination_id,
        derive_message_id,
    )

    base = CoordinationEnvelope(
        coordination_id=derive_coordination_id(seed="inv"),
        message=CoordinationMessage(
            message_id=derive_message_id(seed="inv:m"),
            message_type=CoordinationMessageType.NOTIFICATION,
            sender_id="s",
            recipient=CoordinationRecipient(recipient_id="r"),
            payload=CoordinationPayload(content_type="application/json"),
            priority=CoordinationPriority.NORMAL,
        ),
        direction=CoordinationDirection.AGENT_TO_AGENT,
        status=CoordinationStatus.DISPATCHED,
        sequence=1,
        runtime_instance_id=uuid.uuid4(),
        correlation_id=None,
        parent_coordination_id=None,
        parent_message_id=None,
        request_id=None,
        tenant_id=None,
        governance_decision_id=None,
        governance_chain_id=None,
        created_at=datetime.now(timezone.utc),
        dispatched_at=datetime.now(timezone.utc),
    )
    assert dataclasses.replace(
        base, status=CoordinationStatus.DISPATCHED
    ).is_delivered
    assert dataclasses.replace(
        base, status=CoordinationStatus.DEGRADED
    ).is_delivered
    assert not dataclasses.replace(
        base, status=CoordinationStatus.DENIED
    ).is_delivered
    assert not dataclasses.replace(
        base, status=CoordinationStatus.POLICY_DENIED
    ).is_delivered
    assert not dataclasses.replace(
        base, status=CoordinationStatus.TOPOLOGY_DENIED
    ).is_delivered
    assert not dataclasses.replace(
        base, status=CoordinationStatus.FAILED
    ).is_delivered
    assert not dataclasses.replace(
        base, status=CoordinationStatus.PENDING
    ).is_delivered


def test_metadata_keys_are_namespaced() -> None:
    for key in CoordinationMetadataKey:
        assert key.value.startswith("coordination."), (
            f"metadata key {key.value!r} is not namespaced under "
            f"'coordination.*'"
        )


def test_governance_action_catalogue_pinned() -> None:
    assert {m.value for m in CoordinationGovernanceAction} == {
        "coordination.request",
        "coordination.response",
        "coordination.notification",
        "coordination.handoff",
        "coordination.signal",
    }


def test_coordination_package_does_not_import_agents_or_supervisor() -> None:
    """Architectural invariant: coordination is a strict leaf.

    The substrate composes with `GovernanceRuntime` via injection and
    nothing else from the runtime layer. Importing `app.agents` or
    `app.supervisor` from inside `app.coordination` would couple the
    substrate to higher layers and break Rules 1 / 5 / 7.
    """
    pkg_path = Path(app.coordination.__file__).parent
    for mod_info in pkgutil.walk_packages(
        [str(pkg_path)], prefix="app.coordination."
    ):
        module = importlib.import_module(mod_info.name)
        source_file = getattr(module, "__file__", None)
        if source_file is None:
            continue
        # Inspect the file's source — substrate must not import from
        # agents or supervisor.
        text = Path(source_file).read_text()
        assert "from app.agents" not in text, (
            f"{mod_info.name} imports from app.agents — coordination "
            f"must be a strict leaf"
        )
        assert "from app.supervisor" not in text, (
            f"{mod_info.name} imports from app.supervisor — "
            f"coordination must not write into supervisors"
        )
        assert "import app.agents" not in text
        assert "import app.supervisor" not in text
