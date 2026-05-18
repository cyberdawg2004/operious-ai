"""Authority/tenant coexistence invariant (Branch A).

Single canonical implementation of the rule first established by
Wedge B2 (boundary contracts) and replicated inline across
B6 (supervisor) and B7 (coordination). Branch A centralises the
rule under :mod:`app.identity` so every orchestration contract
that carries both the legacy ``tenant_id`` and the typed
:class:`AuthorityContext` agrees with one shared decoder.

The rule
────────
* ``authority is None``  → legal (legacy-only caller).
* ``tenant_id is None``  → legal (typed-only caller).
* ``authority.tenant_id is None`` → legal (typed surface omitted
  the tenant axis).
* Both sides populated AND
  ``authority.tenant_id != tenant_id``       → ``ValueError``.

Rationale: during the typed-ingress transition we accept either
surface, but reject contradictory pairs at the contract boundary
so no orchestration runtime ever has to coalesce two disagreeing
authority sources.
"""

from __future__ import annotations

from app.identity.authority import AuthorityContext


def check_tenant_authority_coexistence(
    *,
    contract_name: str,
    authority: AuthorityContext | None,
    tenant_id: str | None,
) -> None:
    """Raise ``ValueError`` if ``authority`` and ``tenant_id``
    each name a different tenant. Silent when either side is
    ``None`` or when they agree."""
    if (
        authority is not None
        and authority.tenant_id is not None
        and tenant_id is not None
        and authority.tenant_id != tenant_id
    ):
        raise ValueError(
            f"{contract_name}: authority.tenant_id and tenant_id "
            f"must agree when both are supplied (got "
            f"authority.tenant_id={authority.tenant_id!r}, "
            f"tenant_id={tenant_id!r})"
        )


__all__ = ["check_tenant_authority_coexistence"]
