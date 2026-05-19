"""Transport contracts for the v1 auth endpoints.

Pure Pydantic schemas. They define the JSON wire format and
nothing else:

* No imports from ``app.db.*`` — schemas never carry ORM types.
* No imports from ``app.services.*`` — schemas never depend on
  orchestration.
* Conversion FROM ``AuthorityContext`` happens via the explicit
  :meth:`MePrincipalResponse.from_authority` classmethod so the
  mapping is a single, reviewable surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.identity.authority import AuthorityContext
from app.middleware.authority_context import (
    AUTHORITY_SOURCE_ANONYMOUS,
    AUTHORITY_SOURCE_HEADER,
    AUTHORITY_SOURCE_VERIFIED,
)

AuthoritySource = Literal["verified", "header", "anonymous"]


class MePrincipalResponse(BaseModel):
    """Response shape for ``GET /v1/auth/me``.

    Snapshot of the request's :class:`AuthorityContext` (the four
    identity axes + capabilities) plus the substrate's
    attribution of HOW that authority was established
    (``verified`` Auth0 token vs upstream-trusted ``X-*-ID``
    header vs ``anonymous``).

    Wire-stable: renaming any field is a breaking change to every
    frontend that consumes the auth-me endpoint (SDK + login
    flow + tenant-switcher UI). The schema is FROZEN (Pydantic
    ``model_config={"frozen": True}``) so handlers cannot mutate
    responses post-construction.

    NOT carried on the wire (intentional):

    * ``issuer`` / ``issued_at`` / ``expires_at`` / opaque
      ``claims`` from :class:`VerifiedIdentity` — those are
      audit-provenance fields the frontend has no use for. They
      stay in ``request.state`` for the duration of the request
      so audit / supervisor surfaces can still read them.
    """

    model_config = ConfigDict(frozen=True)

    principal_id: str | None = Field(
        ...,
        description=(
            "Verified principal identifier (typically the JWT "
            "``sub`` claim). ``None`` when the request is "
            "anonymous or when the upstream identity provider "
            "supplied no principal."
        ),
    )
    tenant_id: str | None = Field(
        ...,
        description=(
            "Verified tenant identifier (typically the JWT "
            "``tenant_id`` claim or its namespaced custom-claim "
            "equivalent). ``None`` when the request carries no "
            "tenant axis."
        ),
    )
    organization_id: str | None = Field(
        ...,
        description=(
            "Verified organisation identifier within the tenant "
            "(sub-tenant scope). ``None`` when the request carries "
            "no org axis."
        ),
    )
    environment_id: str | None = Field(
        ...,
        description=(
            "Verified environment identifier "
            "(``production`` / ``staging`` / …). ``None`` when "
            "the request carries no environment axis."
        ),
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description=(
            "Verified RBAC capabilities granted by the upstream "
            "identity provider. Sorted lexicographically for "
            "deterministic response equality across runs."
        ),
    )
    authority_source: AuthoritySource = Field(
        ...,
        description=(
            "Provenance of the bound authority. ``verified`` = an "
            "``AuthProvider`` verified the Bearer credential; "
            "``header`` = an upstream stamped canonical "
            "``X-*-ID`` identity headers; ``anonymous`` = no "
            "authority was bound."
        ),
    )

    @classmethod
    def from_authority(
        cls,
        authority: AuthorityContext,
        *,
        source: str,
    ) -> "MePrincipalResponse":
        """Project an :class:`AuthorityContext` into the wire shape.

        Capabilities are sorted lexicographically so two requests
        that bind the same authority produce byte-equal JSON
        responses. The ``source`` string is validated against the
        constitutional enum from
        :mod:`app.middleware.authority_context` — passing an
        unrecognised value raises :class:`ValueError` rather than
        emitting a response that lies to the caller about how
        their identity was established.
        """
        if source not in (
            AUTHORITY_SOURCE_VERIFIED,
            AUTHORITY_SOURCE_HEADER,
            AUTHORITY_SOURCE_ANONYMOUS,
        ):
            raise ValueError(
                f"unsupported authority_source: {source!r}"
            )
        return cls(
            principal_id=(
                str(authority.principal_id)
                if authority.principal_id is not None
                else None
            ),
            tenant_id=(
                str(authority.tenant_id)
                if authority.tenant_id is not None
                else None
            ),
            organization_id=(
                str(authority.organization_id)
                if authority.organization_id is not None
                else None
            ),
            environment_id=(
                str(authority.environment_id)
                if authority.environment_id is not None
                else None
            ),
            capabilities=sorted(authority.capabilities),
            authority_source=source,  # type: ignore[arg-type]
        )


__all__ = [
    "AuthoritySource",
    "MePrincipalResponse",
]
