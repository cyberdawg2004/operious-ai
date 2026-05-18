"""Per-request :class:`AuthorityResolution` adapter (Phase 2 / P2-A).

Every orchestration runtime entry method needs to collapse the
two coexisting authority surfaces (typed ``authority`` and legacy
``tenant_id``) into a single, attributed :class:`AuthorityResolution`
exactly once at the top of the call. This helper is the canonical
form of that one-liner — runtimes call::

    resolution = request_authority_resolution(request)

and then read ``resolution.tenant_id`` / ``resolution.source``
instead of ``request.tenant_id`` / no-source-attribution.

Constitutional positioning
──────────────────────────
* Reads are by ``getattr`` so the helper is contract-agnostic. Any
  request that exposes ``authority`` and/or ``tenant_id`` (the
  Branch A surface) works without per-contract wiring.
* ``observed_tenant_id`` is an explicit parameter — runtimes that
  carry an underlying-execution observation (e.g.,
  ``AgentExecutionTrace.tenant_id``) pass it in. The default
  ``None`` collapses to the B6/B7 supervisor + coordination
  semantics.
* Pure function. Replay-safe. No I/O.
"""

from __future__ import annotations

from typing import Any

from app.identity.authority import (
    AuthorityResolution,
    resolve_authority,
)


def request_authority_resolution(
    request: Any,
    *,
    observed_tenant_id: str | None = None,
) -> AuthorityResolution:
    """Resolve the request's effective tenant authority + source.

    Args:
        request: Any orchestration request contract carrying
            ``authority`` and/or ``tenant_id``. Absent attributes
            collapse to ``None`` per ``resolve_authority``.
        observed_tenant_id: Optional underlying-execution tenant
            (fallback when neither typed nor legacy is supplied).

    Returns:
        :class:`AuthorityResolution` — singular tenant_id + source.
    """
    return resolve_authority(
        typed=getattr(request, "authority", None),
        legacy_tenant_id=getattr(request, "tenant_id", None),
        observed_tenant_id=observed_tenant_id,
    )


__all__ = ["request_authority_resolution"]
