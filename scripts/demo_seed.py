#!/usr/bin/env python3
"""
Operious AI Demo Data Reset and Verification Script

Verifies that the canonical Anker demo sessions exist in the target
tenant and are in the expected production schema state. Non-canonical
sessions are reported but never deleted.

Usage:
    python scripts/demo_seed.py [options]

Options:
    --dry-run         Preview all actions without writing to DB
    --verify-only     Check state and exit. No modifications.
    --tenant ID       Target tenant (default: anker-pilot)
    --archive-others  Print archive warning for non-canonical sessions
    --database-url    Override DATABASE_URL

Environment:
    ALEMBIC_DATABASE_URL  Owner DB URL, preferred for verification
    DATABASE_URL          App DB URL, fallback for read verification

This script reads credentials from environment or the explicit
--database-url option only. Never hardcode credentials here.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeAlias, cast

import asyncpg

DEFAULT_TENANT_ID = "anker-pilot"

# The five canonical Anker demo sessions.
# These IDs are permanent. Never change them.
CANONICAL_SESSIONS: dict[str, dict[str, str | float]] = {
    "df6139ba-81fa-5f1d-9b3e-ceba6e7bb135": {
        "scenario": "charging_allow",
        "expected_confidence": 0.93,
    },
    "5bb139de-079b-5c20-a2da-3660b203a576": {
        "scenario": "refund_over_limit",
        "expected_confidence": 0.97,
    },
    "79b38add-3086-55f1-9820-db820697fb13": {
        "scenario": "arabic_language",
        "expected_confidence": 0.82,
    },
    "2432a590-f7bc-5d5d-97f9-94a7d0039851": {
        "scenario": "product_defect",
        "expected_confidence": 0.91,
    },
    "2e16bdcc-c518-504e-952c-b4e3d11cad41": {
        "scenario": "ambiguous_review",
        "expected_confidence": 0.82,
    },
}

ARCHIVE_WARNING = """WARNING: Archiving non-canonical sessions requires a
dedicated lifecycle_phase value (e.g. 'archived') which
does not exist in the current schema. Run with
--verify-only to check demo state without modification.
To clean up non-canonical sessions, a future migration
is required to add archive support."""

Connection: TypeAlias = asyncpg.Connection


@dataclass(frozen=True)
class CanonicalSessionStatus:
    present: bool
    scenario: str
    tenant_id: str | None
    lifecycle_phase: str | None
    opened_at: datetime | None
    event_count: int | None
    has_governance_decision: bool


@dataclass(frozen=True)
class NonCanonicalSession:
    session_id: str
    lifecycle_phase: str
    opened_at: datetime
    event_count: int
    has_governance_decision: bool


async def verify_canonical_sessions(
    conn: Connection,
    tenant_id: str,
) -> dict[str, dict[str, object]]:
    """
    Checks each canonical session ID.
    Returns:
      {
        session_id: {
          "present": bool,
          "lifecycle_phase": str | None,
          "opened_at": datetime | None,
          "event_count": int | None,
          "has_governance_decision": bool,
        }
      }
    """

    statuses: dict[str, dict[str, object]] = {}
    for session_id, config in CANONICAL_SESSIONS.items():
        row = await conn.fetchrow(
            """
            SELECT
                s.session_id::text AS session_id,
                s.tenant_id,
                s.lifecycle_phase,
                s.opened_at,
                count(e.event_id)::int AS event_count,
                coalesce(bool_or(e.governance_decision_id IS NOT NULL), false)
                    AS has_governance_decision
            FROM operational_sessions s
            LEFT JOIN session_events e ON e.session_id = s.session_id
            WHERE s.session_id = $1
            GROUP BY s.session_id, s.tenant_id, s.lifecycle_phase, s.opened_at
            """,
            session_id,
        )
        scenario = str(config["scenario"])
        if row is None:
            statuses[session_id] = _status_to_dict(
                CanonicalSessionStatus(
                    present=False,
                    scenario=scenario,
                    tenant_id=None,
                    lifecycle_phase=None,
                    opened_at=None,
                    event_count=None,
                    has_governance_decision=False,
                )
            )
            continue

        row_tenant_id = _row_str(row, "tenant_id")
        statuses[session_id] = _status_to_dict(
            CanonicalSessionStatus(
                present=row_tenant_id == tenant_id,
                scenario=scenario,
                tenant_id=row_tenant_id,
                lifecycle_phase=_row_str(row, "lifecycle_phase"),
                opened_at=_row_datetime(row, "opened_at"),
                event_count=_row_int(row, "event_count"),
                has_governance_decision=_row_bool(
                    row,
                    "has_governance_decision",
                ),
            )
        )
    return statuses


async def find_non_canonical_sessions(
    conn: Connection,
    tenant_id: str,
) -> list[dict[str, object]]:
    """
    Returns all sessions for tenant_id that are not in
    CANONICAL_SESSIONS. These are test/development sessions.
    """

    rows = await conn.fetch(
        """
        SELECT
            s.session_id::text AS session_id,
            s.lifecycle_phase,
            s.opened_at,
            count(e.event_id)::int AS event_count,
            coalesce(bool_or(e.governance_decision_id IS NOT NULL), false)
                AS has_governance_decision
        FROM operational_sessions s
        LEFT JOIN session_events e ON e.session_id = s.session_id
        WHERE s.tenant_id = $1
        GROUP BY s.session_id, s.lifecycle_phase, s.opened_at
        ORDER BY s.opened_at
        """,
        tenant_id,
    )
    canonical_ids = set(CANONICAL_SESSIONS)
    sessions: list[dict[str, object]] = []
    for row in rows:
        session_id = _row_str(row, "session_id")
        if session_id is None or session_id in canonical_ids:
            continue
        session = NonCanonicalSession(
            session_id=session_id,
            lifecycle_phase=_row_str(row, "lifecycle_phase") or "unknown",
            opened_at=_row_datetime(row, "opened_at")
            or datetime.fromtimestamp(0, tz=timezone.utc),
            event_count=_row_int(row, "event_count") or 0,
            has_governance_decision=_row_bool(row, "has_governance_decision"),
        )
        sessions.append(_non_canonical_to_dict(session))
    return sessions


async def archive_non_canonical_sessions(
    conn: Connection,
    tenant_id: str,
    dry_run: bool,
) -> int:
    """
    Archives (does not delete) non-canonical sessions.
    In dry-run: prints what would be archived, makes no writes.
    Returns count of sessions archived/would-archive.

    The current production schema has no archive flag and no
    dedicated lifecycle_phase for archived sessions, so this function
    intentionally performs no writes in every mode.
    """

    del dry_run
    non_canonical = await find_non_canonical_sessions(conn, tenant_id)
    print(ARCHIVE_WARNING)
    return len(non_canonical)


def print_status_report(
    canonical_status: dict[str, dict[str, object]],
    non_canonical: list[dict[str, object]],
    dry_run: bool,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> None:
    """
    Prints a clean status report for the demo tenant.
    """

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    now = now.replace("+00:00", "Z")

    print("=" * 44)
    print("OPERIOUS AI DEMO STATUS REPORT")
    print(f"Tenant: {tenant_id} | {now}")
    print(f"Dry-run: {'YES' if dry_run else 'NO'}")
    print("=" * 44)
    print()
    print("CANONICAL SESSIONS (5 required):")
    for session_id, config in CANONICAL_SESSIONS.items():
        scenario = str(config["scenario"])
        status = canonical_status.get(session_id, {})
        present = bool(status.get("present"))
        phase = _optional_display(status.get("lifecycle_phase"))
        opened = _format_opened(status.get("opened_at"))
        label = "FOUND" if present else "MISSING"
        print(
            f"{label}: {scenario:<18} {_short_session_id(session_id):<13} "
            f"phase={phase:<10} opened={opened}"
        )
    print()
    print(f"NON-CANONICAL SESSIONS: {len(non_canonical)}")
    print(
        "(archiving requires a future migration — run --archive-others "
        "for details)"
    )
    print()
    if _demo_ready(canonical_status):
        phases = {
            str(status.get("lifecycle_phase"))
            for status in canonical_status.values()
            if status.get("present")
        }
        phase_summary = ", ".join(sorted(phases)) if phases else "unknown"
        print("DEMO HEALTH: READY")
        print(f"All 5 canonical sessions present. Phase: {phase_summary}.")
    else:
        print("DEMO HEALTH: NOT READY")
        print("One or more canonical sessions are missing or outside tenant scope.")
    print()
    print("=" * 44)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Operious AI canonical Anker demo sessions without "
            "rerunning LLM classification or deleting data."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all actions without writing to DB.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Check state and exit. No modifications.",
    )
    parser.add_argument(
        "--tenant",
        default=DEFAULT_TENANT_ID,
        help="Target tenant ID. Defaults to anker-pilot.",
    )
    parser.add_argument(
        "--archive-others",
        action="store_true",
        help="Warn about archive support for non-canonical sessions.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override ALEMBIC_DATABASE_URL/DATABASE_URL.",
    )
    args = parser.parse_args()

    database_url = _resolve_database_url(cast(str | None, args.database_url))
    if database_url is None:
        print(
            "ERROR: set ALEMBIC_DATABASE_URL or DATABASE_URL, or pass "
            "--database-url.",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(
            _async_main(
                database_url=database_url,
                tenant_id=str(args.tenant),
                dry_run=bool(args.dry_run),
                archive_others=bool(args.archive_others),
            )
        )
    except (OSError, asyncpg.PostgresError) as exc:
        print(f"ERROR: database verification failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - script boundary exit code.
        print(f"ERROR: unexpected verification failure: {exc}", file=sys.stderr)
        return 3


async def _async_main(
    *,
    database_url: str,
    tenant_id: str,
    dry_run: bool,
    archive_others: bool,
) -> int:
    normalized_url = _normalize_database_url(database_url)
    conn = cast(Connection, await asyncpg.connect(normalized_url))
    try:
        canonical_status = await verify_canonical_sessions(conn, tenant_id)
        non_canonical = await find_non_canonical_sessions(conn, tenant_id)
        print_status_report(
            canonical_status=canonical_status,
            non_canonical=non_canonical,
            dry_run=dry_run,
            tenant_id=tenant_id,
        )
        if archive_others:
            print()
            await archive_non_canonical_sessions(
                conn,
                tenant_id=tenant_id,
                dry_run=dry_run,
            )
            return 0
        return 0 if _demo_ready(canonical_status) else 1
    finally:
        await conn.close()


def _resolve_database_url(override_url: str | None) -> str | None:
    if override_url:
        return override_url
    return os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get(
        "DATABASE_URL"
    )


def _normalize_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _status_to_dict(status: CanonicalSessionStatus) -> dict[str, object]:
    return {
        "present": status.present,
        "scenario": status.scenario,
        "tenant_id": status.tenant_id,
        "lifecycle_phase": status.lifecycle_phase,
        "opened_at": status.opened_at,
        "event_count": status.event_count,
        "has_governance_decision": status.has_governance_decision,
    }


def _non_canonical_to_dict(
    session: NonCanonicalSession,
) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "lifecycle_phase": session.lifecycle_phase,
        "opened_at": session.opened_at,
        "event_count": session.event_count,
        "has_governance_decision": session.has_governance_decision,
    }


def _demo_ready(canonical_status: dict[str, dict[str, object]]) -> bool:
    if set(canonical_status) != set(CANONICAL_SESSIONS):
        return False
    return all(bool(status.get("present")) for status in canonical_status.values())


def _short_session_id(session_id: str) -> str:
    return f"{session_id[:8]}-..."


def _format_opened(value: object) -> str:
    if not isinstance(value, datetime):
        return "missing"
    opened = value
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    return opened.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _optional_display(value: object) -> str:
    if value is None:
        return "missing"
    return str(value)


def _row_str(row: asyncpg.Record, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    return str(value)


def _row_int(row: asyncpg.Record, key: str) -> int | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(value)


def _row_bool(row: asyncpg.Record, key: str) -> bool:
    value = row[key]
    if isinstance(value, bool):
        return value
    return bool(value)


def _row_datetime(row: asyncpg.Record, key: str) -> datetime | None:
    value = row[key]
    if isinstance(value, datetime):
        return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
