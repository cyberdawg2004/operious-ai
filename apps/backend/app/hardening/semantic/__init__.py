"""Semantic-overlap detection helpers."""

from app.hardening.semantic.validator import (
    OwnershipInvariantValidator,
    validate_authority_ownership,
)

__all__ = [
    "OwnershipInvariantValidator",
    "validate_authority_ownership",
]
