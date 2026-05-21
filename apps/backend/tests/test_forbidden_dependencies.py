"""Phase 2.2 — Forbidden-dependency manifest invariants.

These tests are the executable contract for what may live in
`apps/backend/requirements.txt`. They guard the constitutionalised
dependency surface produced by Phase 2.2 against drift:

1. **Forbidden distributions**: a fixed set of package families is
   permanently banned (autonomous-agent / orchestration frameworks,
   vector-store duplicates, runtime cluster SDKs, Supabase / BaaS,
   product analytics SDKs). Any of them re-appearing in
   `requirements.txt` fails CI.

2. **Transitional distributions**: a small, explicitly-tracked set of
   vendor LLM SDKs and retry libraries are kept on disk so that
   quarantined modules under `app/_deprecated/` remain loadable. Their
   presence is asserted exactly so it is impossible to silently drop
   them without updating the contract — that would be a meaningful
   change requiring deliberate review (e.g. when `_deprecated/` is
   eventually deleted in a later phase).

3. **Lockfile shape**: every entry must be `name==version` (PEP 440
   pinned), with one explicit Celery Redis transport extra. No floating
   versions, no VCS URLs, no other extras. This is
   what reproducibility looks like in practice.

All three checks read `requirements.txt` directly so the test is
robust against a stale lockfile produced by `pip freeze` from a dirty
venv.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = REPO_BACKEND_ROOT / "requirements.txt"


# Distribution names are matched case-insensitively because PyPI is
# case-insensitive on the project name.
FORBIDDEN_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        # Autonomous-agent / orchestration frameworks.
        "crewai",
        "instructor",
        "langchain",
        "langchain-core",
        "langchain-protocol",
        "langgraph",
        "langgraph-checkpoint",
        "langgraph-prebuilt",
        "langgraph-sdk",
        "langsmith",
        "mcp",
        # Vector-store duplicates (legacy memory pipeline).
        "chromadb",
        "lancedb",
        "lance-namespace",
        "lance-namespace-urllib3-client",
        "pyiceberg",
        # Runtime cluster SDK at the application layer.
        "kubernetes",
        # BaaS coupling.
        "supabase",
        "supabase-auth",
        "supabase-functions",
        "postgrest",
        "realtime",
        "storage3",
        # Product-analytics SDK.
        "posthog",
    }
)


# Transitional dependencies that are KEPT on disk so quarantined
# modules under `app/_deprecated/` remain syntactically loadable.
# `tests/test_transitional_vendor_isolation.py` enforces that no
# constitutional substrate imports them. Removing one of these from
# `requirements.txt` is allowed only when its dependents inside
# `app/_deprecated/` are deleted in the same change.
TRANSITIONAL_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "openai",
        "anthropic",
        "tenacity",
        "backoff",
    }
)


_REQUIREMENT_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[(?P<extras>[A-Za-z0-9][A-Za-z0-9._-]*)\])?"
    r"==(?P<version>[A-Za-z0-9._+!-]+)\s*$"
)
_ALLOWED_EXTRAS: frozenset[tuple[str, str]] = frozenset(
    {("celery", "redis")}
)


def _parsed_requirements() -> list[tuple[str, str, int]]:
    """Return the parsed `(distribution, version, line_no)` triples
    from `requirements.txt`, ignoring blank lines and comments. Raises
    AssertionError on any line that is not a strict PEP 440 pin.
    """
    text = REQUIREMENTS_PATH.read_text(encoding="utf-8")
    parsed: list[tuple[str, str, int]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _REQUIREMENT_LINE.match(stripped)
        assert match, (
            f"requirements.txt:{idx} is not a strict `name==version` "
            f"pin: {line!r}"
        )
        name = match.group("name").lower()
        extras = match.group("extras")
        if extras is not None:
            extra = extras.lower()
            assert (name, extra) in _ALLOWED_EXTRAS, (
                f"requirements.txt:{idx} uses unsupported extras: "
                f"{line!r}"
            )
        parsed.append((name, match.group("version"), idx))
    return parsed


def _distribution_names() -> set[str]:
    return {name for name, _version, _line in _parsed_requirements()}


# ─── Invariant 1: forbidden distributions absent ─────────────────────


def test_forbidden_distributions_are_not_pinned() -> None:
    pinned = _distribution_names()
    forbidden = {dist.lower() for dist in FORBIDDEN_DISTRIBUTIONS}
    intruders = sorted(pinned & forbidden)
    assert not intruders, (
        "FORBIDDEN distributions present in requirements.txt — Phase 2.2 "
        "forbids them: " + ", ".join(intruders)
    )


# ─── Invariant 2: transitional distributions accounted-for ──────────


def test_transitional_distributions_are_pinned_exactly() -> None:
    pinned = _distribution_names()
    transitional = {dist.lower() for dist in TRANSITIONAL_DISTRIBUTIONS}
    missing = sorted(transitional - pinned)
    assert not missing, (
        "transitional distributions are missing from requirements.txt; "
        "remove them from TRANSITIONAL_DISTRIBUTIONS in this test file "
        "in the same change: " + ", ".join(missing)
    )


# ─── Invariant 3: every line is a strict PEP 440 pin ────────────────


def test_every_requirement_is_a_strict_pin() -> None:
    # Parsing succeeds (asserts inside `_parsed_requirements`); reaching
    # here means every non-comment line matched `name==version`.
    parsed = _parsed_requirements()
    assert parsed, "requirements.txt parsed empty — manifest broken"


# ─── Invariant 4: no duplicate pins ─────────────────────────────────


def test_no_duplicate_distribution_pins() -> None:
    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for name, _version, line_no in _parsed_requirements():
        if name in seen:
            duplicates.append(
                f"{name} (lines {seen[name]} and {line_no})"
            )
        else:
            seen[name] = line_no
    assert not duplicates, (
        "duplicate distribution pins in requirements.txt: "
        + ", ".join(duplicates)
    )
