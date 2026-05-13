"""Database package.

`base`    - DeclarativeBase + reusable mixins.
`session` - async engine, session factory, FastAPI dependency.
`models`  - ORM model definitions (must be imported so they register
            against `Base.metadata` for Alembic autogenerate).
"""

from app.db.base import Base, TimestampMixin
from app.db.session import AsyncSessionLocal, engine, get_db_session

__all__ = [
    "Base",
    "TimestampMixin",
    "engine",
    "AsyncSessionLocal",
    "get_db_session",
]
