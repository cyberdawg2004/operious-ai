"""Coordination substrate ORM package (PR-B4).

Backs the Postgres implementation of
:class:`CoordinationPersistenceProtocol`. Registered at the
migration layer (``migrations/env.py``), not through
``app.db.models``, to avoid the circular-import hazard documented
in ``app/db/models/__init__.py``.
"""

from app.coordination.db.models import CoordinationEnvelopeRow

__all__ = ["CoordinationEnvelopeRow"]
