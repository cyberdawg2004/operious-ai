"""Boundary substrate ORM package (PR-B7)."""

from app.boundary.db.models import (
    BoundaryEgressRow,
    BoundaryIngressRow,
)

__all__ = ["BoundaryEgressRow", "BoundaryIngressRow"]
