"""Boundary normalisation utilities.

* `BoundaryNormalizer`              — orchestrates an adapter and
                                       canonicalises its output.
* canonicalisation helpers          — `canonicalize_payload`,
                                       `canonicalize_metadata`,
                                       `content_fingerprint`.
"""

from app.boundary.normalization.canonicalize import (
    canonicalize_metadata,
    canonicalize_payload,
    content_fingerprint,
)
from app.boundary.normalization.normalizer import (
    BoundaryNormalizer,
)

__all__ = [
    "BoundaryNormalizer",
    "canonicalize_metadata",
    "canonicalize_payload",
    "content_fingerprint",
]
