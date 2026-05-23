"""SQLAlchemy declarative foundation.

This module is the SINGLE source of truth for the project's ORM
metadata. It owns:

* `Base`                  — the one `DeclarativeBase` every model
                            inherits from.
* `MetaData` + naming     — deterministic constraint names so Alembic
                            migrations are reproducible across machines.
* Reusable column mixins  — composable building blocks
                            (`TimestampMixin`, `UUIDPrimaryKeyMixin`)
                            that entities opt into without ever defining
                            a second `Base` or a second `MetaData`.

No model definitions live here. Models live under `app/db/models/`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All ORM models MUST inherit from this class. There is exactly one
    `Base` and exactly one `MetaData` in the entire project — Alembic's
    autogenerate, migration determinism, and runtime introspection all
    depend on that invariant.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Reusable `id: uuid.UUID` primary key column.

    * UUID v4, generated application-side so inserts never need a
      round-trip just to learn their own identifier.
    * Stored as the native PostgreSQL `UUID` type — indexed, compact,
      and safe to expose at the API boundary.
    * Lives on a mixin (not on `Base`) so entities that need a different
      identity strategy (composite keys, natural keys) are free to opt
      out without paying for an unused column.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Adds `created_at` / `updated_at` columns.

    Server-side defaults (`func.now()`) so timestamps remain correct
    when rows are inserted by tooling outside the ORM (psql, Alembic
    data migrations, COPY, etc.).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "Base",
    "NAMING_CONVENTION",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
