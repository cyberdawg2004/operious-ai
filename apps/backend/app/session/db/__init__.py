"""Session substrate ORM package.

Persistence-layer ORM rows backing the Postgres implementation of
:class:`SessionPersistenceProtocol`. The shapes are PRIVATE to the
substrate's persistence layer — runtime code never touches these
classes directly. :class:`PostgresSessionPersistence` is the only
legal consumer.

Per ``app/db/models/__init__.py``, per-substrate ORM modules are
registered at the migration layer (``migrations/env.py``) rather
than through ``app.db.models`` to avoid circular-import hazards
when a substrate-scoped test is the first module pytest collects.
"""

from app.session.db.models import (
    SessionCorrelationRow,
    SessionEventRow,
    SessionRow,
)

__all__ = [
    "SessionCorrelationRow",
    "SessionEventRow",
    "SessionRow",
]
