"""Coordination-topology persistence protocol — storage-agnostic.

Implementations MUST:

* be write-once per ``evaluation_id`` (re-recording the same id
  raises `CoordinationTopologyPersistenceError`);
* return records sorted by
  ``(runtime_instance_id, sequence)`` ascending from
  `query_evaluations`;
* never mutate already-persisted records.

NO event sourcing, NO brokers, NO distributed queues.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.coordination.topology.persistence.models import (
    CoordinationTopologyQuery,
    RecordPage,
)
from app.coordination.topology.persistence.records import (
    CoordinationTopologyRecord,
)


@runtime_checkable
class CoordinationTopologyPersistenceProtocol(Protocol):
    """Persistence contract for coordination-topology evaluations."""

    async def record_evaluation(
        self, record: CoordinationTopologyRecord
    ) -> None:
        """Persist `record`. Write-once per `evaluation_id`."""

    async def get_evaluation(
        self, evaluation_id: str
    ) -> CoordinationTopologyRecord | None:
        """Return the record for `evaluation_id`, or None if absent."""

    async def query_evaluations(
        self, query: CoordinationTopologyQuery
    ) -> RecordPage[CoordinationTopologyRecord]:
        """Return a deterministically-ordered page of records."""


__all__ = ["CoordinationTopologyPersistenceProtocol"]
