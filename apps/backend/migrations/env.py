"""Alembic environment, async-aware.

Wires Alembic to the same `Settings` object and `Base.metadata` the
running application uses, so:

* Migrations always target the configured environment's database.
* `alembic revision --autogenerate` sees every model registered on
  `app.db.base.Base.metadata`.
* Online migrations use the asyncpg driver via `AsyncEngine`.

Run `alembic upgrade head` (or `alembic revision --autogenerate -m ...`)
from the repository root.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

# Import models so they register on Base.metadata. Every new model
# module must be imported here (directly or transitively) to be picked
# up by autogenerate.
#
# ``app.db.models`` registers the cross-cutting infrastructure ORM
# (``system_health_checks``). Per-substrate ORM modules are imported
# explicitly below so they bind to ``Base.metadata`` for
# autogenerate without going through ``app/db/models/__init__.py``
# (see the rationale in that file's docstring — touching per-substrate
# ORM at app.db init time creates a circular-import hazard when a
# substrate test is the first module pytest collects).
from app.db import models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.governance.db import models as _governance_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.session.db import models as _session_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.coordination.db import models as _coordination_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.arbitration.db import models as _arbitration_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# Inject the live async DSN into Alembic's config so the engine factory
# below uses the right driver and credentials.
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emits SQL)."""
    context.configure(
        url=settings.database_url_sync,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations online against the configured async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
