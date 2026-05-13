"""Database package.

Public surface:

* `Base`, `TimestampMixin`, `UUIDPrimaryKeyMixin` — declarative
  foundation (see `app.db.base`).
* `engine`, `AsyncSessionLocal`, `get_db_session`, `dispose_engine` —
  async runtime (see `app.db.session`).

Importing this package has one critical side effect: it imports the
`models` subpackage, which in turn imports every concrete ORM model so
they all register on `Base.metadata`. This single import is what Alembic
autogenerate and any runtime metadata reflection rely on.
"""

from app.db import models as models  # noqa: F401  — registration side effect
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import (
    AsyncSessionLocal,
    dispose_engine,
    engine,
    get_db_session,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "engine",
    "AsyncSessionLocal",
    "get_db_session",
    "dispose_engine",
]
