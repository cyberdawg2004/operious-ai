"""Repository base class.

Holds the request-scoped `AsyncSession` and nothing else. This is the
deliberate, durable shape: each concrete repository expresses its
queries explicitly so the persistence surface stays auditable.

Resist the temptation to add generic `get`, `list`, `create`, `update`,
`delete` helpers here. Generic CRUD on a base class becomes the single
hardest layer to evolve later — every query inherits assumptions
(filtering, soft-delete semantics, pagination shape) that one of the
domains will eventually need to break. The brief explicitly rules this
out for Sprint D, and the rule is correct.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Common repository plumbing.

    Subclasses receive their `AsyncSession` via constructor (wired by
    a dependency provider in `app.dependencies.database` /
    `app.dependencies.services`; the pre-Phase-2.1 repository factory
    was removed with the legacy quarantine) and expose intent-named
    query methods.
    Repositories MUST NOT call
    `session.commit()` or `session.rollback()` — that is the service
    layer's job.
    """

    __slots__ = ("session",)

    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session


__all__ = ["BaseRepository"]
