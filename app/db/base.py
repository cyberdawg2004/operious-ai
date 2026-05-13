"""SQLAlchemy declarative foundation.

A single `Base` (SQLAlchemy 2.0 `DeclarativeBase`) plus reusable mixins.
Models live in `app/db/models.py` (and any future submodules) and all
inherit from `Base` so Alembic's autogenerate sees a single metadata.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# A consistent naming convention keeps Alembic migrations deterministic
# across machines and database backends.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All ORM models MUST inherit from this class so they share one
    `MetaData` (required by Alembic autogenerate and by the naming
    convention above).
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """Adds `created_at` / `updated_at` columns.

    Server-side defaults (`func.now()`) so timestamps are correct even
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


__all__ = ["Base", "TimestampMixin", "NAMING_CONVENTION"]
