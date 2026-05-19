"""Tenant-scoped repository base for Postgres-backed substrates.

Constitutional contract
-----------------------
Every tenant-scoped persistence backend MUST honour
``docs/governance/tenant-scoped-persistence.md`` — point reads return
``None`` and list reads return an empty page when the row's
``tenant_id`` does not match the caller-supplied
``expected_tenant_id``. Invisibility MUST be indistinguishable from
non-existence so an attacker authenticated as tenant ``T'`` cannot
enumerate tenant ``T``'s records by guessing IDs.

This module provides:

* :class:`TenantScopedRepository` — a thin subclass of
  :class:`app.repositories.base.BaseRepository` that exposes a
  single helper, :meth:`TenantScopedRepository._clamp_tenant`, which
  appends the ``WHERE tenant_id = $expected`` predicate to a
  SQLAlchemy ``Select`` statement when an ``expected_tenant_id`` is
  supplied. Substrate-specific repositories compose this helper into
  their own ``get_*`` / ``query_*`` methods; the helper is purely
  declarative and does NOT execute SQL on its own.

The class is intentionally tiny. The repository pattern in
``app.repositories.base`` deliberately resists generic CRUD helpers
(``get`` / ``list`` / ``create``) because every substrate has
substrate-specific filter shapes. The tenant-clamp helper is the
ONE shared mechanism that survives that rule — every tenant-scoped
substrate's read path needs identical clamping semantics, and the
helper is small enough to inspect at a glance.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select

from app.db.base import TenantScopedMixin
from app.repositories.base import BaseRepository

_M = TypeVar("_M", bound=TenantScopedMixin)


class TenantScopedRepository(BaseRepository):
    """Repository base that clamps queries to a caller-supplied tenant.

    Subclasses MUST own the SQL — there is no generic ``get`` or
    ``list`` here. The single helper this class provides is
    :meth:`_clamp_tenant`, which is the canonical implementation of
    the row-level isolation predicate from
    ``docs/governance/tenant-scoped-persistence.md``.

    Usage::

        from sqlalchemy import select

        class SessionRepository(TenantScopedRepository):
            async def get_session(
                self,
                session_id: SessionId,
                *,
                expected_tenant_id: str | None = None,
            ) -> SessionRecord | None:
                stmt = select(SessionRow).where(
                    SessionRow.session_id == session_id
                )
                stmt = self._clamp_tenant(
                    stmt, SessionRow, expected_tenant_id
                )
                row = (await self.session.execute(stmt)).scalar_one_or_none()
                return None if row is None else row.to_record()
    """

    @staticmethod
    def _clamp_tenant(
        stmt: Select[tuple[_M]],
        model: type[_M],
        expected_tenant_id: str | None,
    ) -> Select[tuple[_M]]:
        """Append ``WHERE model.tenant_id = $expected_tenant_id`` if supplied.

        Returns ``stmt`` unchanged when ``expected_tenant_id is
        None`` — substrate-internal reconstruction tools, cold-storage
        replay, and admin endpoints legitimately read without a
        tenant clamp (see the doctrine doc). Returns the predicate-
        narrowed statement otherwise.

        The helper is intentionally static: it has no dependency on
        the repository's :attr:`session` and is therefore safe to
        call from inside transaction-less query builders, batch
        scripts, or unit tests that mock the session entirely.

        Args:
            stmt: A SQLAlchemy ``Select`` whose target row type
                inherits from :class:`TenantScopedMixin`.
            model: The ORM model class that owns the
                ``tenant_id`` column. Passing the class explicitly
                (instead of inferring it from the statement) keeps
                the helper compatible with multi-join queries
                whose outermost ``select()`` may not carry an
                obvious primary entity.
            expected_tenant_id: The tenant id the caller's
                authority resolved to. ``None`` means "no clamp".

        Returns:
            Either ``stmt`` unchanged or ``stmt.where(model.tenant_id
            == expected_tenant_id)``.
        """
        if expected_tenant_id is None:
            return stmt
        return stmt.where(model.tenant_id == expected_tenant_id)


__all__ = ["TenantScopedRepository"]
