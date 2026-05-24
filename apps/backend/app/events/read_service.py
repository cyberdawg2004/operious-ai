"""Read-only service facade for canonical operational events."""

from __future__ import annotations

from app.events.identity import EventId
from app.events.persistence import (
    OperationalEventPage,
    OperationalEventPersistenceProtocol,
    OperationalEventQuery,
)
from app.events.replay import OperationalReplayRuntime, OperationalReplayTrace
from app.events.runtime import OperationalEventRuntime


class OperationalEventReader:
    """Read/replay facade over the canonical event fabric runtime."""

    def __init__(
        self,
        *,
        persistence: OperationalEventPersistenceProtocol,
    ) -> None:
        self._event_runtime = OperationalEventRuntime(persistence=persistence)
        self._replay_runtime = OperationalReplayRuntime(
            event_runtime=self._event_runtime
        )

    async def list_events(
        self,
        query: OperationalEventQuery,
        *,
        expected_tenant_id: str,
    ) -> OperationalEventPage:
        return await self._event_runtime.list_events(
            query,
            expected_tenant_id=expected_tenant_id,
        )

    async def load_replay_trace(
        self,
        *,
        event_id: EventId | None,
        root_event_id: EventId | None,
        query: OperationalEventQuery,
        expected_tenant_id: str,
    ) -> OperationalReplayTrace:
        if event_id is not None:
            return await self._replay_runtime.load_event_trace(
                event_id,
                expected_tenant_id=expected_tenant_id,
            )
        if root_event_id is not None:
            return await self._replay_runtime.load_causal_trace(
                root_event_id,
                expected_tenant_id=expected_tenant_id,
            )
        if query.governance_decision_id is not None:
            page = await self._event_runtime.list_events(
                OperationalEventQuery(
                    governance_decision_id=query.governance_decision_id,
                    limit=1,
                    offset=0,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            if page.events:
                return await self._replay_runtime.load_causal_trace(
                    page.events[0].causality.root_event_id,
                    expected_tenant_id=expected_tenant_id,
                )
        return await self._replay_runtime.load_window(
            query,
            expected_tenant_id=expected_tenant_id,
        )


__all__ = ["OperationalEventReader"]
