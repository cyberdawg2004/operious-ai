"""Governance substrate ORM package.

Persistence-layer ORM rows backing the Postgres implementation of
``BaseGovernanceRepository``. The shapes are PRIVATE to the
substrate's persistence layer — runtime code never touches these
classes directly. The ``app/governance/persistence/postgres.py``
repository is the only legal consumer; everything else goes through
the Protocol contract in
``app/governance/persistence/repository.py``.

Models registered here MUST also be re-imported from
``app/db/models/__init__.py`` so they bind to ``Base.metadata`` for
Alembic autogenerate. The import-time side effect of
``app/db/__init__.py`` then guarantees autogenerate sees every
governance table.
"""

from app.governance.db.models import (
    EnforcementActionRow,
    GovernanceDecisionRow,
    GovernanceTraceRow,
)

__all__ = [
    "EnforcementActionRow",
    "GovernanceDecisionRow",
    "GovernanceTraceRow",
]
