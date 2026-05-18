"""Constitutional regression tests for ``app.identity.runtime``.

Wedge B8 (Phase 1) pins:

1. The runtime accessor module exposes exactly three symbols:
   ``get_request_authority``, ``set_request_authority``,
   ``reset_request_authority``.
2. ``get_request_authority`` returns ``None`` outside any explicit
   ``set_*`` binding (background tasks, REPL, tests).
3. ``set_request_authority`` returns a reset token that
   ``reset_request_authority`` consumes to restore the previous
   value.
4. Concurrent ``asyncio`` tasks each see their own
   ``AuthorityContext`` — the ContextVar provides per-task
   isolation as documented.
5. The runtime module is part of the identity LEAF substrate and
   only imports from within ``app.identity``.
"""

from __future__ import annotations

import asyncio
import pathlib

import app.identity.runtime as runtime
from app.identity import (
    AuthorityContext,
    get_request_authority,
    reset_request_authority,
    set_request_authority,
)


def test_runtime_module_public_surface() -> None:
    """Pin the public surface so the runtime stays focused."""
    assert set(runtime.__all__) == {
        "get_request_authority",
        "set_request_authority",
        "reset_request_authority",
    }


def test_unset_returns_none() -> None:
    """Outside any explicit binding the accessor returns ``None``."""
    assert get_request_authority() is None


def test_set_then_get_round_trips() -> None:
    authority = AuthorityContext.from_raw(tenant_id="acme")
    token = set_request_authority(authority)
    try:
        assert get_request_authority() is authority
    finally:
        reset_request_authority(token)
    assert get_request_authority() is None


def test_reset_restores_previous_binding() -> None:
    """Nested set/reset must produce LIFO restoration semantics."""
    outer = AuthorityContext.from_raw(tenant_id="outer")
    inner = AuthorityContext.from_raw(tenant_id="inner")
    outer_token = set_request_authority(outer)
    try:
        assert get_request_authority() is outer
        inner_token = set_request_authority(inner)
        try:
            assert get_request_authority() is inner
        finally:
            reset_request_authority(inner_token)
        assert get_request_authority() is outer
    finally:
        reset_request_authority(outer_token)
    assert get_request_authority() is None


def test_runtime_module_is_leaf() -> None:
    """``app.identity.runtime`` must remain inside the identity
    substrate. Any import from a sibling substrate would invert
    the dependency direction and break the "Authority Singularity"
    core law (consumers reach for the runtime, not the other way
    around)."""
    forbidden_prefixes = (
        "app.governance",
        "app.session",
        "app.hardening",
        "app.arbitration",
        "app.boundary",
        "app.coordination",
        "app.agents",
        "app.supervisor",
        "app.organizational_intelligence",
        "app.api",
        "app.services",
        "app.repositories",
        "app.db",
        "app.middleware",
        "app.observability",
        "app.dependencies",
        "app.core",
    )
    runtime_path = pathlib.Path(runtime.__file__)
    text = runtime_path.read_text(encoding="utf-8")
    for forbidden in forbidden_prefixes:
        assert f"from {forbidden}" not in text, (
            f"app.identity.runtime imports from forbidden "
            f"sibling substrate {forbidden}; identity substrate "
            "must remain a leaf"
        )
        assert f"import {forbidden}" not in text, (
            f"app.identity.runtime imports forbidden "
            f"sibling substrate {forbidden}; identity substrate "
            "must remain a leaf"
        )


def test_concurrent_tasks_see_isolated_authority() -> None:
    """``ContextVar`` per-task isolation: two coroutines running
    concurrently must each observe their own binding without
    cross-leakage. This pins the "exactly ONE AuthorityContext per
    request" guarantee for the middleware."""

    a = AuthorityContext.from_raw(tenant_id="a")
    b = AuthorityContext.from_raw(tenant_id="b")
    observed: dict[str, AuthorityContext | None] = {}

    async def worker(name: str, ctx: AuthorityContext) -> None:
        token = set_request_authority(ctx)
        try:
            # Yield control so the other worker definitely runs
            # interleaved before we read back.
            await asyncio.sleep(0)
            observed[name] = get_request_authority()
        finally:
            reset_request_authority(token)

    async def main() -> None:
        await asyncio.gather(worker("a", a), worker("b", b))

    asyncio.run(main())

    assert observed["a"] is a
    assert observed["b"] is b
    # Outside the workers, the parent task's view is unchanged.
    assert get_request_authority() is None
