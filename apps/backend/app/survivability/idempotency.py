"""Transport-layer idempotency primitive (P2-E).

Distinct from :class:`app.boundary.idempotency.BoundaryIdempotencyRegistry`
(which is a domain-specific replay-record store for boundary events).
This primitive answers the HTTP question: "did this caller already
submit a request with this Idempotency-Key in the recent past, and if
so what response did they get?".

The shape mirrors industry convention (Stripe's idempotency-key
contract, IETF draft ``draft-ietf-httpapi-idempotency-key-header``):

* The client provides ``Idempotency-Key: <key>`` on unsafe methods.
* The server hashes the request body + method + path; on first
  observation it stores the hash + response; on retry with the same
  key it returns the stored response if the hash matches, else
  rejects with 409 Conflict.

Constitutional boundaries
─────────────────────────
* The primitive does NOT decide which methods are "unsafe" — that's
  a policy concern for the middleware that adopts it.
* The primitive does NOT format a 409 response — that's a
  :class:`ProblemDetails` concern.
* The primitive does NOT touch authority. The store is keyed by
  ``(tenant_id, idempotency_key)`` so cross-tenant collisions are
  structurally impossible.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, NewType


IdempotencyKey = NewType("IdempotencyKey", str)


# Permissive but bounded format: 1–255 chars of URL-safe characters.
# Mirrors the IETF draft "key" production rule.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-.:]{1,255}$")


class IdempotencyKeyError(ValueError):
    """Raised when a candidate string is not a valid idempotency key."""


def coerce_idempotency_key(value: str) -> IdempotencyKey:
    """Validate and tag ``value`` as an :class:`IdempotencyKey`.

    Idempotency keys are bounded to 255 chars of
    ``[A-Za-z0-9_\\-.:]`` so they survive logging and persistence
    without escaping concerns.
    """
    if not isinstance(value, str):
        raise IdempotencyKeyError(
            f"idempotency key must be str; got {type(value).__name__}"
        )
    if not _KEY_PATTERN.match(value):
        raise IdempotencyKeyError(
            f"idempotency key {value!r} violates format constraint"
        )
    return IdempotencyKey(value)


@dataclass(frozen=True, slots=True)
class IdempotencyPolicy:
    """Operational policy for a :class:`InMemoryIdempotencyStore`.

    Attributes:
        ttl: How long a stored record remains valid. Defaults to 24h
            (industry convention). The store evicts records older
            than ``ttl`` lazily on lookup.
        max_records: Optional cap on the in-memory store size. When
            set, the oldest record is evicted when the cap is
            exceeded.
    """

    ttl: timedelta = timedelta(hours=24)
    max_records: int | None = None

    def __post_init__(self) -> None:
        if self.ttl.total_seconds() <= 0:
            raise ValueError("IdempotencyPolicy.ttl must be positive")
        if self.max_records is not None and self.max_records < 1:
            raise ValueError(
                "IdempotencyPolicy.max_records must be None or >= 1"
            )


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """One observed request keyed by ``(tenant_id, idempotency_key)``.

    Attributes:
        idempotency_key: The client-supplied key.
        tenant_id: Tenant scope; the store is partitioned by tenant
            so cross-tenant collisions are structurally impossible.
        request_fingerprint: Stable hash of method + path + body
            (the primitive does not compute this — the caller
            supplies it).
        response_status: Stored HTTP status of the original response.
        response_body: Opaque structured response payload.
        first_seen_at: When the record was first written.
        last_seen_at: When the record was most recently observed.
        observation_count: How many times the key was seen.
        metadata: Opaque propagated payload (eg. correlation_id).
    """

    idempotency_key: IdempotencyKey
    tenant_id: str | None
    request_fingerprint: str
    response_status: int
    response_body: Mapping[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime
    observation_count: int = 1
    metadata: Mapping[str, Any] = field(default_factory=dict)


class InMemoryIdempotencyStore:
    """Async-safe in-memory idempotency store.

    Pluggable contract: any concrete store (Redis-backed, etc.) must
    expose the same ``get`` / ``record_first`` / ``record_observation``
    methods. Adoption (middleware wiring) is deferred to a later
    wedge.
    """

    __slots__ = ("_records", "_lock", "_policy")

    def __init__(
        self, *, policy: IdempotencyPolicy | None = None
    ) -> None:
        self._records: dict[
            tuple[str | None, IdempotencyKey], IdempotencyRecord
        ] = {}
        self._lock = asyncio.Lock()
        self._policy = policy or IdempotencyPolicy()

    async def get(
        self,
        *,
        idempotency_key: IdempotencyKey,
        tenant_id: str | None,
        now: datetime | None = None,
    ) -> IdempotencyRecord | None:
        """Return the stored record, if any and not expired."""
        ts = now or datetime.now(tz=timezone.utc)
        async with self._lock:
            record = self._records.get((tenant_id, idempotency_key))
            if record is None:
                return None
            if ts - record.first_seen_at > self._policy.ttl:
                # Lazy eviction.
                del self._records[(tenant_id, idempotency_key)]
                return None
            return record

    async def record_first(
        self,
        *,
        idempotency_key: IdempotencyKey,
        tenant_id: str | None,
        request_fingerprint: str,
        response_status: int,
        response_body: Mapping[str, Any],
        now: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> IdempotencyRecord:
        """Atomically register a brand-new key.

        Raises:
            KeyError: If the key already exists for the tenant.
        """
        ts = now or datetime.now(tz=timezone.utc)
        async with self._lock:
            existing = self._records.get(
                (tenant_id, idempotency_key)
            )
            if existing is not None and ts - existing.first_seen_at <= self._policy.ttl:
                raise KeyError(
                    f"idempotency key already registered: "
                    f"{idempotency_key}"
                )
            self._evict_if_needed_locked()
            record = IdempotencyRecord(
                idempotency_key=idempotency_key,
                tenant_id=tenant_id,
                request_fingerprint=request_fingerprint,
                response_status=response_status,
                response_body=dict(response_body),
                first_seen_at=ts,
                last_seen_at=ts,
                observation_count=1,
                metadata=dict(metadata or {}),
            )
            self._records[(tenant_id, idempotency_key)] = record
            return record

    async def record_observation(
        self,
        *,
        idempotency_key: IdempotencyKey,
        tenant_id: str | None,
        now: datetime | None = None,
    ) -> IdempotencyRecord:
        """Atomically bump the observation count.

        Raises:
            KeyError: If the key has not been registered.
        """
        ts = now or datetime.now(tz=timezone.utc)
        async with self._lock:
            existing = self._records.get(
                (tenant_id, idempotency_key)
            )
            if existing is None:
                raise KeyError(
                    f"idempotency key not registered: "
                    f"{idempotency_key}"
                )
            updated = IdempotencyRecord(
                idempotency_key=existing.idempotency_key,
                tenant_id=existing.tenant_id,
                # Immutable across observations.
                request_fingerprint=existing.request_fingerprint,
                response_status=existing.response_status,
                response_body=existing.response_body,
                first_seen_at=existing.first_seen_at,
                # Updated on each observation.
                last_seen_at=ts,
                observation_count=existing.observation_count + 1,
                metadata=existing.metadata,
            )
            self._records[(tenant_id, idempotency_key)] = updated
            return updated

    def _evict_if_needed_locked(self) -> None:
        """Evict the oldest record when ``max_records`` is exceeded."""
        cap = self._policy.max_records
        if cap is None or len(self._records) < cap:
            return
        # `dict` preserves insertion order; the oldest record is the
        # first key (lazy approximation — accurate enough for a cap).
        oldest_key = next(iter(self._records))
        del self._records[oldest_key]


__all__ = [
    "IdempotencyKey",
    "IdempotencyKeyError",
    "IdempotencyPolicy",
    "IdempotencyRecord",
    "InMemoryIdempotencyStore",
    "coerce_idempotency_key",
]
