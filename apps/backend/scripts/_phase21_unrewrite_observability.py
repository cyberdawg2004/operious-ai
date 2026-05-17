"""Phase 2.1 — reverse-rewrite for un-quarantined observability modules.

After the initial bulk rewrite, three observability modules were moved
back to the constitutional surface because they are consumed by the
constitutional governance enforcement runtime:

* `app.observability.audit`
* `app.observability.governance_logging`
* `app.observability.governance_metrics`

Files under `app/_deprecated/` that referenced them through the bulk
rewrite (`app._deprecated.observability.audit`, etc.) need to be
flipped back to the constitutional path so the deprecated modules
remain importable as forensic dead code.

This script is committed alongside the Phase 2.1 quarantine commit to
make the reverse rewrite reproducible.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

UNREWRITE_TARGETS: tuple[str, ...] = (
    "audit",
    "governance_logging",
    "governance_metrics",
)


def _build_patterns() -> list[tuple[re.Pattern[str], str]]:
    patterns: list[tuple[re.Pattern[str], str]] = []
    for name in UNREWRITE_TARGETS:
        escaped = re.escape(name)
        patterns.append(
            (
                re.compile(
                    rf"\bfrom app\._deprecated\.observability\.{escaped}\b"
                ),
                f"from app.observability.{name}",
            )
        )
        patterns.append(
            (
                re.compile(
                    rf"\bimport app\._deprecated\.observability\.{escaped}\b"
                ),
                f"import app.observability.{name}",
            )
        )
    return patterns


def main(root: Path) -> int:
    deprecated_root = root / "app" / "_deprecated"
    if not deprecated_root.is_dir():
        print(f"refusing: {deprecated_root} missing", file=sys.stderr)
        return 1
    patterns = _build_patterns()
    changed: list[Path] = []
    for path in deprecated_root.rglob("*.py"):
        original = path.read_text(encoding="utf-8")
        rewritten = original
        for pattern, replacement in patterns:
            rewritten = pattern.sub(replacement, rewritten)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
            changed.append(path)
    print(f"un-rewrote {len(changed)} files under {deprecated_root}")
    for path in changed:
        print(f"  {path.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parent.parent))
