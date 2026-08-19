"""Deterministic PostgreSQL advisory locking for the Northstar seed.

The key is deliberately independent of the fixture contents.  Every fixture
revision for the same canonical tenant therefore serializes on one lock.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


NORTHSTAR_SEED_LOCK_NAMESPACE: Final = "operious:northstar-seed:transaction-lock:v1"
NORTHSTAR_SEED_LOCK_TIMEOUT_MILLISECONDS: Final = 2_000
_CANONICAL_TENANT_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SIGNED_INT64_MIN: Final = -(2**63)
_SIGNED_INT64_MAX: Final = 2**63 - 1


class NorthstarLockKeyError(ValueError):
    """Raised before any database access for a noncanonical tenant ID."""


def derive_northstar_seed_lock_key(tenant_id: str) -> int:
    """Return a stable signed-int64 advisory-lock key for one tenant.

    PostgreSQL's one-argument advisory lock accepts a signed ``bigint``.
    ``sha256`` makes this deterministic across Python processes and hosts,
    unlike ``hash()``.
    """

    if not _CANONICAL_TENANT_ID.fullmatch(tenant_id):
        raise NorthstarLockKeyError("tenant ID must be canonical")
    digest = hashlib.sha256(
        f"{NORTHSTAR_SEED_LOCK_NAMESPACE}|{tenant_id}".encode("utf-8")
    ).digest()
    key = int.from_bytes(digest[:8], byteorder="big", signed=True)
    if not _SIGNED_INT64_MIN <= key <= _SIGNED_INT64_MAX:  # defensive invariant
        raise NorthstarLockKeyError("derived advisory lock key is out of range")
    return key


async def acquire_northstar_seed_transaction_lock(
    session: AsyncSession,
    *,
    tenant_id: str,
    timeout_milliseconds: int = NORTHSTAR_SEED_LOCK_TIMEOUT_MILLISECONDS,
) -> int:
    """Set a transaction-local bound and acquire the tenant's xact lock."""

    if timeout_milliseconds <= 0:
        raise ValueError("lock timeout must be positive")
    key = derive_northstar_seed_lock_key(tenant_id)
    await session.execute(
        text("SELECT set_config('lock_timeout', :timeout, true)"),
        {"timeout": f"{timeout_milliseconds}ms"},
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": key}
    )
    return key


def is_postgres_lock_timeout(error: BaseException) -> bool:
    """Recognize only PostgreSQL's lock-not-available SQLSTATE (55P03)."""

    current: BaseException | object | None = error
    while current is not None:
        sqlstate = getattr(current, "sqlstate", None) or getattr(
            current, "pgcode", None
        )
        if sqlstate == "55P03":
            return True
        current = getattr(current, "orig", None)
    return False


__all__ = [
    "NORTHSTAR_SEED_LOCK_NAMESPACE",
    "NORTHSTAR_SEED_LOCK_TIMEOUT_MILLISECONDS",
    "NorthstarLockKeyError",
    "acquire_northstar_seed_transaction_lock",
    "derive_northstar_seed_lock_key",
    "is_postgres_lock_timeout",
]
