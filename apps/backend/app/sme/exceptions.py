"""SME review runtime exceptions."""

from __future__ import annotations


class SmeReviewError(Exception):
    """Base class for SME review runtime failures."""


class SmeReviewUnavailableError(SmeReviewError):
    """A configured LLM reviewer failed and fail-closed is enabled.

    Callers MUST leave the case in a pending state (not auto-advanced)
    so a human still signs off; the SME recommendation is unavailable.
    """


__all__ = ["SmeReviewError", "SmeReviewUnavailableError"]
