"""Database package.

Public surface:

* `Base`, `TimestampMixin`, `UUIDPrimaryKeyMixin` — declarative
  foundation (see `app.db.base`).
* `engine`, `AsyncSessionLocal`, `dispose_engine` — async runtime
  primitives (see `app.db.session`).

The FastAPI request-scoped session provider lives in
`app.dependencies.database` — this package stays transport-agnostic.

Importing this package has one critical side effect: it imports the
`models` subpackage, which in turn imports every concrete ORM model so
they all register on `Base.metadata`. This single import is what Alembic
autogenerate and any runtime metadata reflection rely on.
"""

from app.db import models as models  # noqa: F401  — registration side effect
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.session import AsyncSessionLocal, dispose_engine, engine

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "engine",
    "AsyncSessionLocal",
    "dispose_engine",
]
