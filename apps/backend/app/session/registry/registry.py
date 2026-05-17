"""`SessionRegistry` — deterministic in-memory session directory.

Discipline:

* Append-only on `register()` — duplicate session ids raise.
* `update()` replaces the apex value object (used when the
  runtime publishes a lifecycle/context/lineage update).
* Iteration order is sorted by `SessionId` string, never
  registration order.

The registry is OPTIONAL — persistence is the substrate's
authoritative store. The registry exists for cheap synchronous
inspection of currently-known sessions in an in-memory deployment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Mapping

from app.session.exceptions import SessionConfigurationError
from app.session.identity import SessionId
from app.session.models.session import OperationalSession


class SessionRegistry:
    """Async-safe deterministic session directory."""

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[SessionId, OperationalSession] = {}
        self._lock = asyncio.Lock()

    async def register(self, session: OperationalSession) -> None:
        async with self._lock:
            if session.identity.session_id in self._records:
                raise SessionConfigurationError(
                    "session already registered: "
                    f"{session.identity.session_id}"
                )
            self._records[session.identity.session_id] = session

    async def update(self, session: OperationalSession) -> None:
        async with self._lock:
            existing = self._records.get(session.identity.session_id)
            if existing is None:
                raise SessionConfigurationError(
                    "cannot update unknown session: "
                    f"{session.identity.session_id}"
                )
            if session.revision <= existing.revision:
                raise SessionConfigurationError(
                    "non-monotonic revision on registry update: "
                    f"existing={existing.revision}, "
                    f"incoming={session.revision}"
                )
            self._records[session.identity.session_id] = session

    async def get(
        self, session_id: SessionId
    ) -> OperationalSession | None:
        return self._records.get(session_id)

    def has(self, session_id: SessionId) -> bool:
        return session_id in self._records

    def ids(self) -> tuple[SessionId, ...]:
        return tuple(
            sorted(self._records.keys(), key=str)
        )

    def iterate(self) -> Iterator[OperationalSession]:
        for session_id in self.ids():
            yield self._records[session_id]

    def snapshot(
        self,
    ) -> Mapping[SessionId, OperationalSession]:
        return dict(self._records)

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["SessionRegistry"]
