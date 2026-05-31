"""Knowledge poisoning review controls.

The scanner is a signal, not the primary defense. Retrieval remains gated by
review status and prompt construction structurally delimits retrieved text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeInjectionPattern:
    category: str
    phrase: str
    description: str


@dataclass(frozen=True, slots=True)
class KnowledgeInjectionScanResult:
    flagged: bool
    categories: tuple[str, ...] = ()
    matched_phrases: tuple[str, ...] = ()


class KnowledgeInjectionScanner(Protocol):
    def scan(self, content: str) -> KnowledgeInjectionScanResult:
        """Return injection signals for tenant-supplied knowledge content."""
        ...


INJECTION_PATTERNS: tuple[KnowledgeInjectionPattern, ...] = (
    KnowledgeInjectionPattern(
        category="instruction_override",
        phrase="ignore previous instructions",
        description="Attempts to override higher-priority model instructions.",
    ),
    KnowledgeInjectionPattern(
        category="instruction_override",
        phrase="disregard all prior instructions",
        description="Attempts to discard the governing prompt contract.",
    ),
    KnowledgeInjectionPattern(
        category="policy_subversion",
        phrase="approve all refunds",
        description="Attempts to subvert refund governance decisions.",
    ),
    KnowledgeInjectionPattern(
        category="policy_subversion",
        phrase="bypass policy",
        description="Attempts to bypass tenant or platform policy controls.",
    ),
    KnowledgeInjectionPattern(
        category="role_manipulation",
        phrase="you are now",
        description="Attempts to redefine the model role from retrieved data.",
    ),
    KnowledgeInjectionPattern(
        category="role_manipulation",
        phrase="system prompt",
        description="References prompt internals from untrusted content.",
    ),
)
"""Maintainable injection signals grouped by defense category.

These phrases intentionally cover instruction override, policy subversion, and
role manipulation. They quarantine for human review; they are not the sole
defense against prompt injection.
"""


class PatternKnowledgeInjectionScanner:
    """Simple deterministic scanner for known prompt-injection signals."""

    def __init__(
        self,
        patterns: tuple[KnowledgeInjectionPattern, ...] = INJECTION_PATTERNS,
    ) -> None:
        self._patterns = patterns

    def scan(self, content: str) -> KnowledgeInjectionScanResult:
        haystack = " ".join(content.lower().split())
        categories: list[str] = []
        phrases: list[str] = []
        for pattern in self._patterns:
            if pattern.phrase in haystack:
                categories.append(pattern.category)
                phrases.append(pattern.phrase)
        return KnowledgeInjectionScanResult(
            flagged=bool(phrases),
            categories=tuple(dict.fromkeys(categories)),
            matched_phrases=tuple(phrases),
        )


__all__ = [
    "INJECTION_PATTERNS",
    "KnowledgeInjectionPattern",
    "KnowledgeInjectionScanResult",
    "KnowledgeInjectionScanner",
    "PatternKnowledgeInjectionScanner",
]
