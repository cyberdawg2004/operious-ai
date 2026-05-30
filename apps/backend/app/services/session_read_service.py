"""Read-only service layer for session timeline data."""

from __future__ import annotations

from app.session.contracts.results import ReconstructSessionResult
from app.session.identity import as_session_id
from app.session.models.timeline import SessionTimeline
from app.session.runtime import SessionRuntime


class SessionReadServiceError(RuntimeError):
    """Raised when a session read cannot be completed."""


class SessionTimelineNotFoundError(SessionReadServiceError):
    """Raised when a session timeline cannot be found."""


class SessionReadService:
    """
    Read-only service layer for session data.
    Wraps SessionRuntime timeline/reconstruction reads.
    Routers call this service; never SessionRuntime directly.
    """

    def __init__(
        self,
        *,
        session_runtime: SessionRuntime,
    ) -> None:
        self._session_runtime = session_runtime

    async def get_timeline(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> SessionTimeline:
        if not expected_tenant_id:
            raise SessionReadServiceError(
                "expected_tenant_id is required for session timeline reads"
            )
        envelope = await self._session_runtime.get_timeline(
            as_session_id(session_id),
            expected_tenant_id=expected_tenant_id,
        )
        if not envelope.is_ok or envelope.result is None:
            raise SessionReadServiceError("timeline read failed")
        result = envelope.result
        if not isinstance(result, ReconstructSessionResult):
            raise SessionReadServiceError("timeline read failed")
        if result.timeline is None:
            raise SessionTimelineNotFoundError("session timeline not found")
        return result.timeline


__all__ = [
    "SessionReadService",
    "SessionReadServiceError",
    "SessionTimelineNotFoundError",
]
