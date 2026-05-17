"""Deterministic in-memory registries.

Both registries are async-safe, append-only on `register()` (with
explicit `update()` for revision changes), and iterate in
sorted-id order. They are OPTIONAL convenience caches in front of
persistence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

from app.organizational_intelligence.exceptions import (
    IntelligenceConfigurationError,
)
from app.organizational_intelligence.identity import (
    CommunicationPatternId,
    SopId,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.models.sop import (
    StandardOperatingProcedure,
)


class SopRegistry:
    """Async-safe deterministic SOP directory."""

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[SopId, StandardOperatingProcedure] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, sop: StandardOperatingProcedure
    ) -> None:
        async with self._lock:
            if sop.sop_id in self._records:
                raise IntelligenceConfigurationError(
                    f"SOP already registered: {sop.sop_id}"
                )
            self._records[sop.sop_id] = sop

    async def update(
        self, sop: StandardOperatingProcedure
    ) -> None:
        async with self._lock:
            existing = self._records.get(sop.sop_id)
            if existing is None:
                raise IntelligenceConfigurationError(
                    f"unknown SOP: {sop.sop_id}"
                )
            if sop.revision <= existing.revision:
                raise IntelligenceConfigurationError(
                    "non-monotonic revision on registry update"
                )
            self._records[sop.sop_id] = sop

    async def get(
        self, sop_id: SopId
    ) -> StandardOperatingProcedure | None:
        return self._records.get(sop_id)

    def has(self, sop_id: SopId) -> bool:
        return sop_id in self._records

    def ids(self) -> tuple[SopId, ...]:
        return tuple(sorted(self._records.keys(), key=str))

    def iterate(self) -> Iterator[StandardOperatingProcedure]:
        for sop_id in self.ids():
            yield self._records[sop_id]

    def __len__(self) -> int:
        return len(self._records)


class CommunicationPatternRegistry:
    """Async-safe deterministic communication-pattern directory."""

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[
            CommunicationPatternId, CommunicationPattern
        ] = {}
        self._lock = asyncio.Lock()

    async def register(
        self, pattern: CommunicationPattern
    ) -> None:
        async with self._lock:
            if pattern.pattern_id in self._records:
                raise IntelligenceConfigurationError(
                    f"pattern already registered: {pattern.pattern_id}"
                )
            self._records[pattern.pattern_id] = pattern

    async def get(
        self, pattern_id: CommunicationPatternId
    ) -> CommunicationPattern | None:
        return self._records.get(pattern_id)

    def has(self, pattern_id: CommunicationPatternId) -> bool:
        return pattern_id in self._records

    def ids(self) -> tuple[CommunicationPatternId, ...]:
        return tuple(sorted(self._records.keys(), key=str))

    def iterate(self) -> Iterator[CommunicationPattern]:
        for pattern_id in self.ids():
            yield self._records[pattern_id]

    def __len__(self) -> int:
        return len(self._records)


__all__ = ["CommunicationPatternRegistry", "SopRegistry"]
