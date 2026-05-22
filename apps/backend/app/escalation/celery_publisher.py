"""Celery-backed escalation publisher."""

from __future__ import annotations

import os
import sys
from typing import Any, cast

from app.escalation.publisher import EscalationPublisher
from app.workers.escalation_tasks import (
    create_governance_escalation,
    create_governance_escalation_runtime,
)


class CeleryEscalationPublisher(EscalationPublisher):
    """Publish escalation intents through worker transport."""

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        task = cast(Any, create_governance_escalation)
        if _running_under_pytest():
            await create_governance_escalation_runtime(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )
        else:
            task.delay(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
            )


def _running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


__all__ = ["CeleryEscalationPublisher"]
