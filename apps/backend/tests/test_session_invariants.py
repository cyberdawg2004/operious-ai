"""Session substrate invariants — Sprint N containment.

These tests are the LAST line of defence against semantic drift.
They MUST stay green; a failure here means the session substrate
has begun to absorb orchestration / execution / sibling-substrate
semantics.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from app.session.runtime.runtime import SessionRuntime


_SESSION_ROOT = Path("app/session")


# ─── Substrate-isolation invariant ──────────────────────────────────


_FORBIDDEN_PARENT_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+app\.(?:agents|supervisor|coordination|"
    r"memory|arbitration|embeddings|replay|tracing|providers|db|"
    r"governance|boundary|orchestration)\b",
    re.MULTILINE,
)
# 2.75-\u03b1: the singular capability legality gate is the ONLY
# cross-substrate surface session is permitted to consume.
_CAPABILITY_GATE_ALLOW_RE = re.compile(
    r"^(?:from|import)\s+app\.governance\.capability\b",
    re.MULTILINE,
)
# PR-B1 / PR-B3: ``app.db.base`` and ``app.db.repository`` are the
# constitutional persistence FOUNDATION (declarative ``Base``,
# mixins, ``TenantScopedRepository`` helper). They are substrate-
# shared infrastructure, not sibling runtimes — importing them
# carries no orchestration / governance / sibling-runtime semantics.
# The exemption is intentionally NARROW: ``app.db.session`` (global
# engine), ``app.db.models`` (cross-cutting ORM registry), and
# ``app.db.partitioning`` (Alembic-facing DDL emitter, consumed by
# migrations not by substrate code) remain forbidden.
_DB_FOUNDATION_ALLOW_RE = re.compile(
    r"^(?:from|import)\s+app\.db\.(?:base|repository)\b",
    re.MULTILINE,
)


def test_no_parent_substrate_imports() -> None:
    """The session substrate MUST NOT import from any sibling runtime.

    The capability legality gate (``app.governance.capability``) is
    the singular cross-substrate exemption — Wedge 2.75-\u03b1
    adopts it at every P2-A entry. The persistence foundation
    (``app.db.base`` / ``app.db.repository``) is the singular
    infrastructure exemption — PR-B3 adopts it from
    ``app/session/db/models.py``.
    """
    offenders: list[str] = []
    for path in _SESSION_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        # Strip the allowed `app.governance.capability` and
        # `app.db.{base,repository}` imports before scanning for
        # forbidden parents — the regex above would otherwise match
        # them on the ``governance`` / ``db`` tokens.
        stripped = _CAPABILITY_GATE_ALLOW_RE.sub("", text)
        stripped = _DB_FOUNDATION_ALLOW_RE.sub("", stripped)
        if _FORBIDDEN_PARENT_IMPORT_RE.search(stripped):
            offenders.append(str(path))
    assert not offenders, (
        f"forbidden cross-substrate imports found in: {offenders}"
    )


# ─── No-orchestration-surface invariant ─────────────────────────────


_FORBIDDEN_RUNTIME_METHODS = {
    "execute",
    "dispatch",
    "schedule",
    "retry",
    "orchestrate",
    "fanout",
    "invoke_agent",
    "invoke_tool",
    "plan",
    "rebalance",
    "rollback",
    "redirect",
    "transition",
    "fire",
    "publish",
    "broadcast",
    "route",
    "trigger",
}


def test_runtime_has_no_orchestration_surfaces() -> None:
    """No methods that imply orchestration / execution authority."""
    public = {
        name
        for name in dir(SessionRuntime)
        if not name.startswith("_")
    }
    for forbidden in _FORBIDDEN_RUNTIME_METHODS:
        assert forbidden not in public, (
            f"SessionRuntime unexpectedly exposes a {forbidden!r} "
            f"method"
        )


def test_runtime_async_surface_pinned() -> None:
    """Pin the runtime's async-method catalogue to prevent surface drift."""
    expected = {
        "open_session",
        "append_event",
        "record_lifecycle",
        "record_context",
        "record_correlation",
        "reconstruct",
        "get_session",
        "get_timeline",
    }
    actual = {
        name
        for name in dir(SessionRuntime)
        if not name.startswith("_")
        and inspect.iscoroutinefunction(
            getattr(SessionRuntime, name)
        )
    }
    assert actual == expected, (
        f"SessionRuntime async surface drifted; "
        f"expected={expected}, actual={actual}"
    )


# ─── Wire-format-stability invariant ────────────────────────────────


@pytest.mark.parametrize(
    "must_export",
    [
        "OperationalSession",
        "SessionContext",
        "SessionCorrelation",
        "SessionIdentity",
        "SessionLifecycle",
        "SessionLineage",
        "SessionTimeline",
        "SessionTimelineEvent",
        "SessionEnvelope",
        "SessionTrace",
        "SessionTraceContext",
        "SessionRuntime",
        "SessionRegistry",
        "SessionReconstructor",
        "InMemorySessionPersistence",
        "SessionPersistenceProtocol",
        "OpenSessionRequest",
        "AppendEventRequest",
        "RecordLifecycleRequest",
        "RecordContextRequest",
        "RecordCorrelationRequest",
        "ReconstructSessionRequest",
        "OpenSessionResult",
        "AppendEventResult",
        "RecordLifecycleResult",
        "RecordContextResult",
        "RecordCorrelationResult",
        "ReconstructSessionResult",
        "SessionLifecyclePhase",
        "SessionEventKind",
        "SessionScope",
        "SessionContinuityMode",
        "SessionReconstructionStatus",
        "SessionCorrelationKind",
        "SessionMetadataKey",
        "derive_session_id",
        "derive_event_id",
        "derive_lineage_id",
        "derive_correlation_id",
        "build_lineage_for_root",
        "build_lineage_for_child",
        "build_event",
        "build_timeline",
        "append_event",
        "is_terminal",
        "next_phase_classification",
        "canonicalize_payload",
        "content_fingerprint",
    ],
)
def test_substrate_exports_canonical_surface(
    must_export: str,
) -> None:
    """`app.session.__all__` is the substrate's external contract."""
    import app.session as substrate

    assert must_export in substrate.__all__
