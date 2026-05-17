"""Internal glob-style pattern matching for rule predicates.

Rules carry glob-shaped pattern fields (``"agent:*"``,
``"tenant:acme:*"``). The matcher is intentionally minimal — only
``*`` (zero-or-more characters) is supported. No regular-expression
surface is exposed to rule authors because:

1. Regex pattern matching is hard to make replay-deterministic across
   Python versions / libraries.
2. A narrow glob surface keeps rule semantics inspectable.
3. Audit dashboards can pretty-print glob patterns easily.

`None` patterns are treated as "do not constrain this axis" — a
common convention across the rule shape.
"""

from __future__ import annotations

import fnmatch


def pattern_matches(pattern: str | None, value: str | None) -> bool:
    """Return True iff `pattern` matches `value`.

    * ``None`` pattern → always matches (unconstrained axis).
    * ``None`` value → matches only the empty / unconstrained
      pattern. A required-tenant pattern against a value-less
      dispatch yields False, surfacing a "missing tenant" finding
      at the evaluator layer.
    * Otherwise → `fnmatch.fnmatchcase` (case-sensitive glob).
    """
    if pattern is None:
        return True
    if value is None:
        return False
    return fnmatch.fnmatchcase(value, pattern)


__all__ = ["pattern_matches"]
