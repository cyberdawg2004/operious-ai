"""Composition helpers for the alert evaluator."""

from __future__ import annotations

from typing import cast

from app.core.admission import admission_thresholds_from_settings
from app.core.config import get_settings
from app.core.redis import get_redis_client
from app.db.session import get_engine, get_owner_session_factory
from app.execution.db.models import ExecutionRow
from app.hardening.admission import AdmissionGate
from app.hardening.admission.gate import AdmissionRedisClient
from app.hardening.observability.alert_evaluator import AlertEvaluator
from app.queues import ALL_QUEUES
from app.runtime.db.models import DeadLetterTaskRow, ProviderCircuitStateRow
from app.runtime.provider_circuit_breaker import ProviderCircuitState


def create_alert_evaluator() -> AlertEvaluator:
    settings = get_settings()

    def admission_gate_factory() -> AdmissionGate:
        return AdmissionGate(
            redis_client=cast(AdmissionRedisClient, get_redis_client()),
            thresholds=admission_thresholds_from_settings(settings),
        )

    return AlertEvaluator(
        settings=settings,
        redis_provider=get_redis_client,
        admission_gate_factory=admission_gate_factory,
        owner_session_context_factory=lambda: get_owner_session_factory()(),
        engine_provider=get_engine,
        queue_names=ALL_QUEUES,
        dead_letter_task_row=DeadLetterTaskRow,
        provider_circuit_state_row=ProviderCircuitStateRow,
        execution_row=ExecutionRow,
        provider_open_state=ProviderCircuitState.OPEN.value,
    )


__all__ = ["create_alert_evaluator"]
