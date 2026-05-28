"""Tool capability tiers.

The enum is intentionally coarse today: read-only diagnostic tools do
not require a per-invocation governance decision, while action tools do.
Future tiers such as high-risk actions can extend this vocabulary
without changing the tool contract from a bool to a richer type later.
"""

from __future__ import annotations

from enum import StrEnum


class ToolCapability(StrEnum):
    """Side-effect capability declared by every registered tool."""

    READ_ONLY = "read_only"
    ACTION = "action"


__all__ = ["ToolCapability"]
