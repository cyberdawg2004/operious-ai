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
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.db.url import build_database_engine_config

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
from app.supervisor.db import models as _supervisor_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.boundary.db import models as _boundary_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.boundary.voice.db import models as _voice_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.execution.db import models as _execution_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.events.db import models as _event_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.tenant.db import models as _tenant_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.knowledge.db import models as _knowledge_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.qa.db import models as _qa_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.escalation.db import models as _escalation_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.approvals.db import models as _approval_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.sop_intelligence.db import models as _sop_intelligence_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.trainer.db import models as _trainer_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.cognition.db import models as _cognition_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.data_protection.db import models as _data_protection_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.observability.db import models as _observability_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.runtime.db import models as _runtime_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.resolution.db import models as _resolution_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.semantic.db import models as _semantic_models  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.work_orders.db import models as _work_order_models  # noqa: F401  # pyright: ignore[reportUnusedImport]

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
engine_config = build_database_engine_config(
    os.environ.get("ALEMBIC_DATABASE_URL") or settings.database_url,
    connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
)

# Inject the live async DSN into Alembic's config so the engine factory
# below uses the right driver and credentials.
config.set_main_option("sqlalchemy.url", engine_config.async_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emits SQL)."""
    context.configure(
        url=engine_config.sync_url,
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
        connect_args=engine_config.connect_args,
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
