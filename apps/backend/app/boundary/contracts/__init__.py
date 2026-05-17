"""Boundary contracts — typed runtime surface."""

from app.boundary.contracts.requests import (
    BoundaryEgressRequest,
    BoundaryIngressRequest,
)
from app.boundary.contracts.results import (
    BoundaryEgressResult,
    BoundaryIngressResult,
)

__all__ = [
    "BoundaryEgressRequest",
    "BoundaryEgressResult",
    "BoundaryIngressRequest",
    "BoundaryIngressResult",
]
