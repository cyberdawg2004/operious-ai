"""Case continuity evaluation for session external handles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.session.enums import SessionLifecyclePhase
from app.session.persistence.models import SessionQuery
from app.session.persistence.repository import SessionPersistenceProtocol

SessionRepository = SessionPersistenceProtocol


class ContinuityOutcome(str, Enum):
    NEW_CASE = "new_case"
    CONTINUATION = "continuation"
    REOPENED_CASE = "reopened_case"


@dataclass(frozen=True, slots=True)
class CaseContinuityResult:
    outcome: ContinuityOutcome
    existing_session_id: str | None = None
    existing_session_phase: str | None = None
    prior_session_id: str | None = None


class CaseContinuityRuntime:
    """Evaluate whether an inbound conversation continues a prior case."""

    def __init__(
        self,
        *,
        session_repository: SessionRepository,
    ) -> None:
        self._session_repository = session_repository

    async def evaluate(
        self,
        *,
        tenant_id: str,
        external_handle: str,
        expected_tenant_id: str,
    ) -> CaseContinuityResult:
        page = await self._session_repository.list_sessions(
            SessionQuery(
                tenant_id=tenant_id,
                external_handle=external_handle,
                limit=1,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        if not page.sessions:
            return CaseContinuityResult(outcome=ContinuityOutcome.NEW_CASE)

        session = page.sessions[0]
        phase = session.lifecycle_phase
        if phase in {
            SessionLifecyclePhase.INITIATED,
            SessionLifecyclePhase.ACTIVE,
            SessionLifecyclePhase.DORMANT,
        }:
            return CaseContinuityResult(
                outcome=ContinuityOutcome.CONTINUATION,
                existing_session_id=str(session.session_id),
                existing_session_phase=phase.value,
            )
        return CaseContinuityResult(
            outcome=ContinuityOutcome.REOPENED_CASE,
            existing_session_id=str(session.session_id),
            existing_session_phase=phase.value,
            prior_session_id=str(session.session_id),
        )


__all__ = [
    "CaseContinuityResult",
    "CaseContinuityRuntime",
    "ContinuityOutcome",
    "SessionRepository",
]
