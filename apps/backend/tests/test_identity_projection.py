"""Constitutional regression tests for ``app.identity.projection``.

Wedge B4 (Phase 1) pins the following invariants:

1. ``project_optional_str(None) != project_optional_str("")``.
   The helper must NEVER collapse the two authority states into the
   same projected seed component.
2. ``project_optional_str`` is replay-deterministic — same input
   produces byte-identical output.
3. The helper is exported on the ``app.identity`` public surface and
   imported by every deterministic identity deriver that accepts an
   optional identifier in its seed.
4. Every fixed deriver (across boundary, session, organizational
   intelligence) derives a DISTINCT UUID for ``None`` vs ``""`` for
   the previously-collapsed parameter, while remaining byte-stable
   under repeated calls with the same input.

These tests are the constitutional contract that pins the closure of
audit defects CO-1, CO-2, and CO-3 (tenant_id propagation audit at
``docs/identity/tenant-propagation-audit.md``). Anyone who weakens
``project_optional_str`` — for example by collapsing the sentinel
back to ``""`` — fails this entire file.
"""

from __future__ import annotations

from app.boundary.identity import (
    derive_event_id as boundary_derive_event_id,
    derive_replay_key,
)
from app.identity import project_optional_str
from app.organizational_intelligence.identity import (
    derive_communication_pattern_id,
    derive_sop_id,
)
from app.session.identity import derive_session_id


# ─── Helper unit invariants ──────────────────────────────────────────


def test_project_optional_str_distinguishes_none_from_empty() -> None:
    """The core constitutional invariant: ``None`` and ``""`` must
    project to distinct seed components.

    If this assertion ever fails, every deterministic identity
    derivation that uses the helper silently collapses two distinct
    authority states. That is the bug Wedge B4 was created to close.
    """
    assert project_optional_str(None) != project_optional_str("")


def test_project_optional_str_passes_non_empty_strings_verbatim() -> None:
    """Non-empty strings must be projected without transformation —
    otherwise tenant-bearing UUIDs change with every projection-helper
    edit. The architecture pin: only ``None`` is transformed."""
    assert project_optional_str("tenant-1") == "tenant-1"
    assert project_optional_str("p-99") == "p-99"
    # Trailing / leading whitespace must NOT be stripped here —
    # ``coerce_*`` is the validation surface; projection is pure.
    assert project_optional_str("  spaced  ") == "  spaced  "


def test_project_optional_str_is_deterministic() -> None:
    """Replay determinism: same input → identical output across
    invocations and across separate calls."""
    assert project_optional_str(None) == project_optional_str(None)
    assert project_optional_str("") == project_optional_str("")
    assert project_optional_str("x") == project_optional_str("x")


def test_project_optional_str_sentinel_is_nul_bounded() -> None:
    """The ``None`` projection must contain NUL bytes — they are
    structurally impossible in identifiers received at the substrate's
    boundaries (forbidden in JSON strings, URLs, shell args, SQL
    identifiers, and every wire protocol the substrate ingresses).
    Without NUL guards the sentinel could collide with a pathological
    user-supplied identifier."""
    sentinel = project_optional_str(None)
    assert "\x00" in sentinel
    assert sentinel != ""
    assert sentinel != "None"
    assert sentinel != "null"


# ─── Boundary derivers: None != "" ───────────────────────────────────


def test_boundary_derive_event_id_distinguishes_none_from_empty_tenant() -> (
    None
):
    """Audit CO-1 closure: ``derive_event_id`` must NEVER collapse
    a tenantless event with an empty-string-tenant event into the
    same ``BoundaryEventId``."""
    none_id = boundary_derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    empty_id = boundary_derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="",
    )
    assert none_id != empty_id


def test_boundary_derive_event_id_none_is_byte_stable() -> None:
    """Same ``tenant_id=None`` input must always derive the same UUID."""
    a = boundary_derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    b = boundary_derive_event_id(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    assert a == b


def test_boundary_derive_replay_key_distinguishes_none_from_empty_tenant() -> (
    None
):
    """Audit CO-1 closure: the idempotency registry's primary index
    must never collide for tenantless vs empty-tenant events."""
    none_key = derive_replay_key(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    empty_key = derive_replay_key(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id="",
    )
    assert none_key != empty_key


def test_boundary_derive_replay_key_none_is_byte_stable() -> None:
    a = derive_replay_key(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    b = derive_replay_key(
        source_type="zendesk",
        external_message_id="evt-1",
        tenant_id=None,
    )
    assert a == b


# ─── Session derivers: None != "" for tenant AND principal ───────────


def test_session_derive_session_id_distinguishes_none_from_empty_tenant() -> (
    None
):
    """Audit CO-2 closure: a tenantless session must NEVER collapse
    onto an empty-tenant session at the deterministic-id layer."""
    none_id = derive_session_id(
        scope="tenant",
        tenant_id=None,
        principal_id="p-1",
        external_handle="h-1",
    )
    empty_id = derive_session_id(
        scope="tenant",
        tenant_id="",
        principal_id="p-1",
        external_handle="h-1",
    )
    assert none_id != empty_id


def test_session_derive_session_id_distinguishes_none_from_empty_principal() -> (
    None
):
    """Audit CO-2 closure (symmetric pair): a principal-less session
    must NEVER collapse onto an empty-principal session."""
    none_id = derive_session_id(
        scope="tenant",
        tenant_id="t-1",
        principal_id=None,
        external_handle="h-1",
    )
    empty_id = derive_session_id(
        scope="tenant",
        tenant_id="t-1",
        principal_id="",
        external_handle="h-1",
    )
    assert none_id != empty_id


def test_session_derive_session_id_distinguishes_none_pair_from_empty_pair() -> (
    None
):
    """The most pathological collapse: BOTH tenant_id AND principal_id
    None vs both "" must produce distinct ``SessionId``s."""
    none_id = derive_session_id(
        scope="tenant",
        tenant_id=None,
        principal_id=None,
        external_handle="h-1",
    )
    empty_id = derive_session_id(
        scope="tenant",
        tenant_id="",
        principal_id="",
        external_handle="h-1",
    )
    assert none_id != empty_id


def test_session_derive_session_id_none_is_byte_stable() -> None:
    a = derive_session_id(
        scope="tenant",
        tenant_id=None,
        principal_id=None,
        external_handle="h-1",
    )
    b = derive_session_id(
        scope="tenant",
        tenant_id=None,
        principal_id=None,
        external_handle="h-1",
    )
    assert a == b


# ─── OI derivers: None != "" ─────────────────────────────────────────


def test_oi_derive_sop_id_distinguishes_none_from_empty_tenant() -> None:
    """Audit CO-3 closure: a tenantless SOP must NEVER collapse onto
    an empty-tenant SOP at the deterministic-id layer."""
    none_id = derive_sop_id(tenant_id=None, external_handle="sop-1")
    empty_id = derive_sop_id(tenant_id="", external_handle="sop-1")
    assert none_id != empty_id


def test_oi_derive_sop_id_none_is_byte_stable() -> None:
    a = derive_sop_id(tenant_id=None, external_handle="sop-1")
    b = derive_sop_id(tenant_id=None, external_handle="sop-1")
    assert a == b


def test_oi_derive_communication_pattern_id_distinguishes_none_from_empty_tenant() -> (
    None
):
    """Audit CO-3 closure: a tenantless communication pattern must
    NEVER collapse onto an empty-tenant pattern at the
    deterministic-id layer."""
    none_id = derive_communication_pattern_id(
        tenant_id=None, pattern_handle="h"
    )
    empty_id = derive_communication_pattern_id(
        tenant_id="", pattern_handle="h"
    )
    assert none_id != empty_id


def test_oi_derive_communication_pattern_id_none_is_byte_stable() -> None:
    a = derive_communication_pattern_id(
        tenant_id=None, pattern_handle="h"
    )
    b = derive_communication_pattern_id(
        tenant_id=None, pattern_handle="h"
    )
    assert a == b


# ─── Public surface ──────────────────────────────────────────────────


def test_project_optional_str_is_exported_from_identity_substrate() -> None:
    """``project_optional_str`` must be available on the ``app.identity``
    public surface so every sibling substrate imports the canonical
    helper instead of inlining its own projection."""
    import app.identity as identity_pkg

    assert hasattr(identity_pkg, "project_optional_str")
    assert "project_optional_str" in identity_pkg.__all__
    assert (
        identity_pkg.project_optional_str is project_optional_str
    )
