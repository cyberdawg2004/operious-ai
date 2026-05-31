#!/usr/bin/env python
"""Release-gate: verify production configuration is READY (S-10, #12).

Wraps :func:`app.core.production_readiness.collect_production_problems` so
CI / deploy pipelines can BLOCK a release whose configuration would boot
on stubbed providers or without security secrets.

Usage::

    python -m scripts.check_production_readiness        # uses live env
    python scripts/check_production_readiness.py

Exit codes:
    0 — configuration is READY (no problems)
    1 — one or more readiness problems (printed to stderr)
"""

from __future__ import annotations

import sys

from app.core.config import Settings
from app.core.production_readiness import collect_production_problems


def evaluate(settings: Settings) -> tuple[bool, tuple[str, ...]]:
    """Return ``(ready, problems)`` for ``settings``."""
    problems = collect_production_problems(settings)
    return (len(problems) == 0, problems)


def main(argv: list[str] | None = None) -> int:
    del argv
    settings = Settings()
    ready, problems = evaluate(settings)
    if ready:
        print("production readiness: READY")
        return 0
    print("production readiness: NOT READY", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
