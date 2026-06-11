"""Transaction-scoped durable escalation publisher."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.escalation.publisher import EscalationPublisher
from app.escalation.runtime import EscalationAgentRuntime
from app.governance.enums import Decision


@dataclass(frozen=True, slots=True)
class _PreparedEscalationIntent:
    governance_decision_id: str
    tenant_id: str
    session_id: str | None
    source_decision: Decision
    escalation_id: str


class DeferredEscalationPublisher(EscalationPublisher):
    """Prepare escalation outbox rows in-transaction; publish after commit."""

    def __init__(
        self,
        *,
        delegate: EscalationPublisher,
        escalation_runtime: EscalationAgentRuntime,
        session: AsyncSession,
        publisher_id: str,
    ) -> None:
        self._delegate = delegate
        self._escalation_runtime = escalation_runtime
        self._session = session
        self._publisher_id = publisher_id
        self._intents: list[_PreparedEscalationIntent] = []

    async def publish_governance_denial(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        prepared = await self._escalation_runtime.prepare_governance_denial_outbox(
            governance_decision_id=governance_decision_id,
            expected_tenant_id=tenant_id,
            session_id=session_id,
            metadata=_outbox_metadata(
                governance_decision_id=governance_decision_id,
                session_id=session_id,
                source_decision=Decision.DENY,
            ),
        )
        self._intents.append(
            _PreparedEscalationIntent(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
                source_decision=Decision.DENY,
                escalation_id=prepared.escalation.escalation_id,
            )
        )

    async def publish_governance_escalation(
        self,
        *,
        governance_decision_id: str,
        tenant_id: str,
        session_id: str | None = None,
    ) -> None:
        prepared = (
            await self._escalation_runtime.prepare_governance_escalation_outbox(
                governance_decision_id=governance_decision_id,
                expected_tenant_id=tenant_id,
                session_id=session_id,
                metadata=_outbox_metadata(
                    governance_decision_id=governance_decision_id,
                    session_id=session_id,
                    source_decision=Decision.ESCALATE,
                ),
            )
        )
        self._intents.append(
            _PreparedEscalationIntent(
                governance_decision_id=governance_decision_id,
                tenant_id=tenant_id,
                session_id=session_id,
                source_decision=Decision.ESCALATE,
                escalation_id=prepared.escalation.escalation_id,
            )
        )

    async def flush(self) -> None:
        pending = list(self._intents)
        self._intents.clear()
        for intent in pending:
            claim = await self._escalation_runtime.claim_outbox_for_escalation(
                escalation_id=intent.escalation_id,
                publisher_id=self._publisher_id,
                expected_tenant_id=intent.tenant_id,
            )
            if not claim.claimed or claim.outbox is None:
                if claim.reason == "outbox_not_publishable:published":
                    continue
                raise EscalationOutboxPublishError(
                    intent.escalation_id,
                    claim.reason or "outbox_claim_refused",
                )
            claim_id = _require_outbox_claim_id(
                escalation_id=intent.escalation_id,
                claim_id=claim.outbox.claim_id,
            )
            await self._session.commit()
            try:
                if intent.source_decision is Decision.ESCALATE:
                    await self._delegate.publish_governance_escalation(
                        governance_decision_id=intent.governance_decision_id,
                        tenant_id=intent.tenant_id,
                        session_id=intent.session_id,
                    )
                else:
                    await self._delegate.publish_governance_denial(
                        governance_decision_id=intent.governance_decision_id,
                        tenant_id=intent.tenant_id,
                        session_id=intent.session_id,
                    )
            except Exception as exc:
                await self._escalation_runtime.mark_outbox_failed(
                    outbox_id=claim.outbox.outbox_id,
                    claim_id=claim_id,
                    error=_bounded_publish_error(exc),
                    expected_tenant_id=intent.tenant_id,
                )
                await self._session.commit()
                raise EscalationOutboxPublishError(
                    intent.escalation_id,
                    _bounded_publish_error(exc),
                ) from exc
            await self._escalation_runtime.mark_outbox_published(
                outbox_id=claim.outbox.outbox_id,
                claim_id=claim_id,
                expected_tenant_id=intent.tenant_id,
            )
            await self._session.commit()


class EscalationOutboxPublishError(RuntimeError):
    """Raised when a committed escalation intent cannot be published."""

    def __init__(self, escalation_id: str, reason: str) -> None:
        super().__init__(
            f"escalation outbox publish failed for {escalation_id}: {reason}"
        )
        self.escalation_id = escalation_id
        self.reason = reason


def _outbox_metadata(
    *,
    governance_decision_id: str,
    session_id: str | None,
    source_decision: Decision,
) -> dict[str, str | None]:
    return {
        "source_governance_decision_id": governance_decision_id,
        "source_session_id": session_id,
        "source_decision": source_decision.value,
    }


def _bounded_publish_error(exc: BaseException) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    if len(message) > 240:
        return f"{message[:237]}..."
    return message


def _require_outbox_claim_id(*, escalation_id: str, claim_id: str | None) -> str:
    if claim_id is None:
        raise EscalationOutboxPublishError(
            escalation_id,
            "claimed escalation outbox is missing claim_id",
        )
    return claim_id


__all__ = [
    "DeferredEscalationPublisher",
    "EscalationOutboxPublishError",
]
