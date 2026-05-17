"""Failure-containment classifier."""

from app.hardening.isolation.containment import (
    FailureContainmentClassifier,
    classify_containment,
)

__all__ = [
    "FailureContainmentClassifier",
    "classify_containment",
]
