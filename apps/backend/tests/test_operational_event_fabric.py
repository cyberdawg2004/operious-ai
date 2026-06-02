# pyright: reportArgumentType=false, reportCallIssue=false
"""P2-D regression tests — institutional event fabric primitive.

Pins the six-axis constitutional model and the append-only,
immutable, causality-linked, replay-safe, authority-attributed
invariants the substrate exists to enforce.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventCausalityError,
    EventChronology,
    EventChronologyError,
    EventFabricError,
    EventId,
    EventPersistenceError,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
    PostgresOperationalEventPersistence,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from tests.conftest import requires_postgres, set_pg_rls_tenant


_RUNTIME = uuid.UUID("11111111-1111-1111-1111-111111111111")
_NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


# ─── derive_event_id ────────────────────────────────────────────────


def test_derive_event_id_is_deterministic() -> None:
    a = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="acme",
        parent_event_id=None,
    )
    b = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="acme",
        parent_event_id=None,
    )
    assert a == b


def test_derive_event_id_distinguishes_none_from_empty_string() -> None:
    """B4 invariant carried forward: ``None != ""`` in deterministic
    derivations."""
    none_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id=None,
        parent_event_id=None,
    )
    empty_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="",
        parent_event_id=None,
    )
    assert none_id != empty_id


def test_derive_event_id_is_uuid_string() -> None:
    eid = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="acme",
        parent_event_id=None,
    )
    assert isinstance(eid, str)
    # UUIDv5 parses cleanly.
    assert uuid.UUID(eid).version == 5


def test_derive_event_id_changes_with_sequence() -> None:
    a = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="acme",
        parent_event_id=None,
    )
    b = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=1,
        tenant_id="acme",
        parent_event_id=None,
    )
    assert a != b


# ─── EventChronology ────────────────────────────────────────────────


def test_event_chronology_rejects_negative_sequence() -> None:
    with pytest.raises(EventChronologyError):
        EventChronology(
            runtime_instance_id=_RUNTIME,
            sequence=-1,
            occurred_at=_NOW,
        )


def test_event_chronology_allows_zero_sequence() -> None:
    chrono = EventChronology(
        runtime_instance_id=_RUNTIME, sequence=0, occurred_at=_NOW
    )
    assert chrono.sequence == 0


def test_event_chronology_is_frozen() -> None:
    chrono = EventChronology(
        runtime_instance_id=_RUNTIME, sequence=0, occurred_at=_NOW
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        chrono.sequence = 1  # type: ignore[misc]


# ─── EventCausality ─────────────────────────────────────────────────


def _root_event_id() -> EventId:
    return derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="acme",
        parent_event_id=None,
    )


def test_event_causality_root_must_have_depth_zero() -> None:
    root_id = _root_event_id()
    with pytest.raises(EventCausalityError):
        EventCausality(
            root_event_id=root_id,
            parent_event_id=None,
            depth=1,
        )


def test_event_causality_child_must_have_depth_positive() -> None:
    root_id = _root_event_id()
    with pytest.raises(EventCausalityError):
        EventCausality(
            root_event_id=root_id,
            parent_event_id=root_id,
            depth=0,
        )


def test_event_causality_rejects_negative_depth() -> None:
    root_id = _root_event_id()
    with pytest.raises(EventCausalityError):
        EventCausality(
            root_event_id=root_id,
            parent_event_id=root_id,
            depth=-1,
        )


def test_event_causality_root_is_root_property() -> None:
    root_id = _root_event_id()
    causality = EventCausality(
        root_event_id=root_id, parent_event_id=None, depth=0
    )
    assert causality.is_root is True


def test_event_causality_child_is_not_root() -> None:
    root_id = _root_event_id()
    causality = EventCausality(
        root_event_id=root_id, parent_event_id=root_id, depth=1
    )
    assert causality.is_root is False


def test_event_causality_is_frozen() -> None:
    root_id = _root_event_id()
    causality = EventCausality(
        root_event_id=root_id, parent_event_id=None, depth=0
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        causality.depth = 1  # type: ignore[misc]


# ─── OperationalEvent ───────────────────────────────────────────────


def _make_event(**overrides) -> OperationalEvent:
    root_id = _root_event_id()
    defaults = dict(
        event_id=root_id,
        operational_act=OperationalAct.SESSION_OPEN,
        substrate=OperationalSubstrate.SESSION,
        causality=EventCausality(
            root_event_id=root_id, parent_event_id=None, depth=0
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME,
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id="acme",
        tenant_authority_source="typed_authority",
    )
    defaults.update(overrides)
    return OperationalEvent(**defaults)  # type: ignore[arg-type]


def test_event_carries_all_six_axes() -> None:
    event = _make_event()
    # WHAT
    assert event.operational_act is OperationalAct.SESSION_OPEN
    # SUBSTRATE
    assert event.substrate is OperationalSubstrate.SESSION
    # AUTHORITY
    assert event.tenant_id == "acme"
    assert event.tenant_authority_source == "typed_authority"
    # CAUSALITY
    assert event.causality.is_root is True
    # CHRONOLOGY
    assert event.chronology.sequence == 0
    assert event.chronology.runtime_instance_id == _RUNTIME
    # LEGALITY (optional — None means no governance evaluation)
    assert event.governance_decision is None


def test_event_with_legality_axis() -> None:
    event = _make_event(
        governance_decision=Decision.ALLOW,
        governance_decision_id="d-1",
    )
    assert event.governance_decision is Decision.ALLOW
    assert event.governance_decision_id == "d-1"


def test_event_is_frozen() -> None:
    event = _make_event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.tenant_id = "other"  # type: ignore[misc]


def test_event_has_no_mutation_methods() -> None:
    """No ``.with_*``, no ``.update``, no ``.replace`` on the type.
    Construction is the only legitimate way to obtain an instance."""
    forbidden = {"replace", "update", "set_metadata", "amend"}
    members = set(dir(OperationalEvent))
    leaked = forbidden & members
    assert not leaked, (
        f"OperationalEvent exposes mutation-style methods: {leaked}"
    )
    for name in members:
        if name.startswith("with_"):
            pytest.fail(
                f"OperationalEvent exposes mutation-style method: "
                f"{name!r}"
            )


def test_event_id_distinguishes_two_chronology_points() -> None:
    e1 = _make_event()
    e2_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=1,
        tenant_id="acme",
        parent_event_id=None,
    )
    e2 = _make_event(
        event_id=e2_id,
        causality=EventCausality(
            root_event_id=e2_id,
            parent_event_id=None,
            depth=0,
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME,
            sequence=1,
            occurred_at=_NOW,
        ),
    )
    assert e1.event_id != e2.event_id


def test_event_metadata_defaults_to_empty_mapping() -> None:
    event = _make_event()
    assert dict(event.metadata) == {}


@requires_postgres
@pytest.mark.asyncio
async def test_schema_version_in_operational_event_metadata(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-event-schema-version"
    runtime_instance_id = uuid.uuid5(
        uuid.NAMESPACE_DNS,
        "operational-event-schema-version",
    )
    event_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=runtime_instance_id,
        sequence=0,
        tenant_id=tenant_id,
        parent_event_id=None,
    )
    event = _make_event(
        event_id=event_id,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        metadata={"source": "test"},
    )
    await set_pg_rls_tenant(pg_session, tenant_id)

    await OperationalEventRuntime(
        persistence=PostgresOperationalEventPersistence(pg_session)
    ).append_event(event, expected_tenant_id=tenant_id)
    row = (
        await pg_session.execute(
            text(
                """
                SELECT metadata
                FROM operational_events
                WHERE event_id = :event_id
                """
            ),
            {"event_id": uuid.UUID(str(event.event_id))},
        )
    ).scalar_one()

    assert row["_schema_version"] == "1"
    assert row["source"] == "test"


def test_event_query_rejects_invalid_replay_windows() -> None:
    with pytest.raises(ValueError):
        OperationalEventQuery(limit=0)
    with pytest.raises(ValueError):
        OperationalEventQuery(offset=-1)
    with pytest.raises(ValueError):
        OperationalEventQuery(
            occurred_after_or_at=_NOW,
            occurred_before_or_at=_NOW.replace(year=2024),
        )


# ─── catalog invariants ─────────────────────────────────────────────


def test_operational_substrate_catalog_covers_hardening_substrate_names() -> None:
    """Drift guard: every value in hardening's substrate enum MUST
    appear in :class:`OperationalSubstrate`. The reverse is not
    required (events catalogs HARDENING itself, hardening does not)."""
    from app.hardening.enums import SubstrateName

    op_values = {s.value for s in OperationalSubstrate}
    hardening_values = {s.value for s in SubstrateName}
    missing = hardening_values - op_values
    assert not missing, (
        f"OperationalSubstrate missing values from hardening: "
        f"{sorted(missing)}"
    )


def test_operational_substrate_includes_hardening() -> None:
    """Constitutional improvement over hardening's enum (which omits
    itself for ownership-boundary reasons)."""
    assert "hardening" in {s.value for s in OperationalSubstrate}


def test_operational_substrate_includes_execution() -> None:
    """Phase 1 execution sovereignty is now a first-class event substrate."""
    assert "execution" in {s.value for s in OperationalSubstrate}


def test_every_operational_act_prefix_maps_to_substrate() -> None:
    """Bijection guard: every ``OperationalAct`` value's prefix
    (everything before ``:``) must be a member of
    :class:`OperationalSubstrate`. Drift here is how event substrates
    silently develop parallel vocabularies."""
    substrates = {s.value for s in OperationalSubstrate}
    for act in OperationalAct:
        prefix = act.value.split(":", 1)[0]
        assert prefix in substrates, (
            f"OperationalAct.{act.name} prefix {prefix!r} is not a "
            "known OperationalSubstrate"
        )


# ─── leaf substrate invariants (source scan) ────────────────────────


def _repo_app_root() -> Path:
    return Path(__file__).resolve().parents[1] / "app"


def _iter_python_sources(root: Path):
    for path in root.rglob("*.py"):
        if "_deprecated" in path.parts:
            continue
        yield path


def _imports_from_module(source: str, prefix: str) -> bool:
    """True iff ``source`` contains a ``from <prefix>...`` import."""
    pat = re.compile(rf"^\s*from\s+{re.escape(prefix)}(\.[\w]+)*\s+import\b", re.M)
    return bool(pat.search(source))


def test_events_substrate_is_a_leaf() -> None:
    """``app/events/`` MUST NOT import from any sibling orchestration
    substrate. Permitted sub-leaves: ``app.identity``,
    ``app.governance.capability.acts``, ``app.governance.enums``."""
    permitted_prefixes = (
        "app.identity",
        "app.events",
        "app.governance.capability.acts",
        "app.governance.enums",
    )
    forbidden_prefixes = (
        "app.agents",
        "app.arbitration",
        "app.boundary",
        "app.coordination",
        "app.hardening",
        "app.organizational_intelligence",
        "app.session",
        "app.supervisor",
        "app.middleware",
        "app.auth",
        "app.observability",
    )
    assert set(permitted_prefixes).isdisjoint(forbidden_prefixes)
    events_root = _repo_app_root() / "events"
    offenders: list[tuple[str, str]] = []
    for py in events_root.rglob("*.py"):
        src = py.read_text(encoding="utf-8")
        for prefix in forbidden_prefixes:
            if _imports_from_module(src, prefix):
                offenders.append(
                    (str(py.relative_to(_repo_app_root())), prefix)
                )
    assert not offenders, (
        f"app/events/ leaked sibling-substrate imports: {offenders}"
    )
    # Sanity: at least the permitted imports are present somewhere.
    for prefix in ("app.identity", "app.governance"):
        any_present = any(
            _imports_from_module(
                py.read_text(encoding="utf-8"), prefix
            )
            for py in events_root.rglob("*.py")
        )
        assert any_present, (
            f"app/events/ unexpectedly does not import {prefix}"
        )


def _calls_dataclasses_replace_on_event(source: str) -> bool:
    """AST scan for ``dataclasses.replace(<name with 'event' in it>, ...)``.

    Ignores docstring / comment mentions; only flags actual call
    sites.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_dc_replace = (
            isinstance(func, ast.Attribute)
            and func.attr == "replace"
            and isinstance(func.value, ast.Name)
            and func.value.id == "dataclasses"
        )
        if not is_dc_replace:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and "event" in first.id.lower():
            return True
    return False


def test_no_module_calls_dataclasses_replace_on_operational_event() -> None:
    """Append-only contract: no module under ``app/`` may call
    ``dataclasses.replace`` on a variable whose name suggests an
    :class:`OperationalEvent`. AST-based; docstrings ignored."""
    app_root = _repo_app_root()
    offenders: list[str] = []
    for py in _iter_python_sources(app_root):
        src = py.read_text(encoding="utf-8")
        if _calls_dataclasses_replace_on_event(src):
            offenders.append(str(py.relative_to(app_root)))
    assert not offenders, (
        f"`dataclasses.replace(event, ...)` call-site(s) found: "
        f"{offenders}"
    )


def test_event_module_public_surface() -> None:
    """Pin the substrate's exported surface."""
    import app.events as events

    assert set(events.__all__) == {
        "EventCausality",
        "EventCausalityError",
        "EventChronology",
        "EventChronologyError",
        "EventFabricError",
        "EventId",
        "EventPersistenceError",
        "InMemoryOperationalEventPersistence",
        "OperationalLineageEdge",
        "OperationalLineageError",
        "OperationalLineageGraph",
        "OperationalLineageRelation",
        "OperationalLineageRuntime",
        "OperationalLineageUnresolvedReference",
        "OperationalEvent",
        "OperationalEventAppendResult",
        "OperationalEventPage",
        "OperationalEventPersistenceProtocol",
        "OperationalEventQuery",
        "OperationalEventRuntime",
        "OperationalReplayFinding",
        "OperationalReplayFindingCode",
        "OperationalReplayFindingSeverity",
        "OperationalReplayRuntime",
        "OperationalReplayStatus",
        "OperationalReplayTrace",
        "OperationalSubstrate",
        "PostgresOperationalEventPersistence",
        "derive_event_id",
        "normalize_operational_lineage",
    }


# ─── exception hierarchy ────────────────────────────────────────────


def test_exception_hierarchy() -> None:
    assert issubclass(EventCausalityError, EventFabricError)
    assert issubclass(EventChronologyError, EventFabricError)
    assert issubclass(EventPersistenceError, EventFabricError)
    assert issubclass(EventFabricError, Exception)
