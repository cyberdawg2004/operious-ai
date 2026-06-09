"""Dead-letter task replay helpers and publisher boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast

from app.queues import (
    QUEUE_DIAGNOSTIC_NORMAL,
    QUEUE_ESCALATION,
    QUEUE_QA,
    QUEUE_SOP_INTELLIGENCE,
    QUEUE_SUPERVISOR,
    QUEUE_WEBHOOK_MAINTENANCE,
)

TASK_DEFAULT_QUEUES: dict[str, str] = {
    "execute_diagnostic_agent": QUEUE_DIAGNOSTIC_NORMAL,
    "create_governance_escalation": QUEUE_ESCALATION,
    "evaluate_session_supervisor": QUEUE_SUPERVISOR,
    "score_supervisor_inspection": QUEUE_QA,
    "propose_sop_intelligence_change": QUEUE_SOP_INTELLIGENCE,
    "recover_stale_executions": QUEUE_WEBHOOK_MAINTENANCE,
    "recover_dead_letter_replays": QUEUE_WEBHOOK_MAINTENANCE,
    "reconcile_stale_execution_outbox": QUEUE_WEBHOOK_MAINTENANCE,
    "reconcile_failed_execution_outbox": QUEUE_WEBHOOK_MAINTENANCE,
    "reconcile_stale_escalation_outbox": QUEUE_WEBHOOK_MAINTENANCE,
    "cleanup_expired_webhook_nonces": QUEUE_WEBHOOK_MAINTENANCE,
    "operious.workers.emit_queue_depth_snapshot": QUEUE_WEBHOOK_MAINTENANCE,
}


class DeadLetterReplayPublisher(Protocol):
    """Transport boundary for replaying one dead-letter task."""

    def publish(
        self,
        *,
        task_name: str,
        kwargs: Mapping[str, Any],
        queue: str,
    ) -> None:
        ...


class CeleryDeadLetterReplayPublisher:
    """Publish arbitrary DLQ task replay through the worker transport."""

    def publish(
        self,
        *,
        task_name: str,
        kwargs: Mapping[str, Any],
        queue: str,
    ) -> None:
        from app.workers.celery_app import celery_app

        cast(Any, celery_app).send_task(
            task_name,
            kwargs=dict(kwargs),
            queue=queue,
        )


def celery_kwargs_for_task(
    *,
    task_name: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    celery_kwargs = metadata.get("celery_kwargs")
    if isinstance(celery_kwargs, Mapping):
        return _mapping_to_dict(cast(Mapping[Any, Any], celery_kwargs))
    extractor = _FALLBACK_KWARG_EXTRACTORS.get(task_name)
    if extractor is None:
        return None
    return extractor(metadata)


def _extract_execute_diagnostic_agent(
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    execution_id = _metadata_str(metadata, "execution_id")
    tenant_id = _metadata_str(metadata, "tenant_id")
    if execution_id is None or tenant_id is None:
        return None
    return {"execution_id": execution_id, "tenant_id": tenant_id}


def _extract_create_governance_escalation(
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    payload = _metadata_dict(metadata, "task_payload")
    governance_decision_id = _first_str(
        payload,
        metadata,
        key="governance_decision_id",
    )
    tenant_id = _first_str(payload, metadata, key="tenant_id")
    if governance_decision_id is None or tenant_id is None:
        return None
    kwargs: dict[str, Any] = {
        "governance_decision_id": governance_decision_id,
        "tenant_id": tenant_id,
    }
    session_id = _first_str(payload, metadata, key="session_id")
    if session_id is not None:
        kwargs["session_id"] = session_id
    return kwargs


def _extract_session_task(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    payload = _metadata_dict(metadata, "task_payload")
    session_id = _first_str(payload, metadata, key="session_id")
    tenant_id = _first_str(payload, metadata, key="tenant_id")
    if session_id is None or tenant_id is None:
        return None
    return {"session_id": session_id, "tenant_id": tenant_id}


def _extract_inspection_task(
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    payload = _metadata_dict(metadata, "task_payload")
    inspection_id = _first_str(payload, metadata, key="inspection_id")
    tenant_id = _first_str(payload, metadata, key="tenant_id")
    if inspection_id is None or tenant_id is None:
        return None
    return {"inspection_id": inspection_id, "tenant_id": tenant_id}


def _extract_sop_intelligence_task(
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    kwargs = _extract_session_task(metadata)
    if kwargs is None:
        return None
    payload = _metadata_dict(metadata, "task_payload")
    inspection_id = _first_str(payload, metadata, key="inspection_id")
    if inspection_id is not None:
        kwargs["inspection_id"] = inspection_id
    return kwargs


def _extract_dispatch_ingress(
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    outbox_id = _metadata_str(metadata, "outbox_id")
    if outbox_id is None:
        return None
    return {"outbox_id": outbox_id}


def _extract_optional_maintenance_kwargs(
    *keys: str,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def extractor(metadata: Mapping[str, Any]) -> dict[str, Any]:
        payload = _metadata_dict(metadata, "task_payload")
        kwargs: dict[str, Any] = {}
        for key in keys:
            value = payload.get(key, metadata.get(key))
            if value is not None:
                kwargs[key] = value
        return kwargs

    return extractor


_FALLBACK_KWARG_EXTRACTORS: dict[
    str,
    Callable[[Mapping[str, Any]], dict[str, Any] | None],
] = {
    "execute_diagnostic_agent": _extract_execute_diagnostic_agent,
    "dispatch_ingress": _extract_dispatch_ingress,
    "create_governance_escalation": _extract_create_governance_escalation,
    "evaluate_session_supervisor": _extract_session_task,
    "score_supervisor_inspection": _extract_inspection_task,
    "propose_sop_intelligence_change": _extract_sop_intelligence_task,
    "recover_stale_executions": _extract_optional_maintenance_kwargs(
        "stale_before",
        "lease_seconds",
        "limit",
        "reason",
    ),
    "recover_dead_letter_replays": _extract_optional_maintenance_kwargs(
        "claimed_before",
        "lease_seconds",
        "limit",
        "tenant_id",
        "reason",
    ),
    "reconcile_stale_execution_outbox": _extract_optional_maintenance_kwargs(
        "stale_before",
        "lease_seconds",
        "limit",
        "tenant_id",
        "reason",
    ),
    "reconcile_failed_execution_outbox": _extract_optional_maintenance_kwargs(
        "failed_before",
        "cooldown_seconds",
        "max_publish_attempts",
        "limit",
        "tenant_id",
        "reason",
    ),
    "reconcile_stale_escalation_outbox": _extract_optional_maintenance_kwargs(
        "stale_before",
        "lease_seconds",
        "limit",
        "tenant_id",
    ),
    "cleanup_expired_webhook_nonces": _extract_optional_maintenance_kwargs(
        "now",
        "limit",
    ),
    "operious.workers.emit_queue_depth_snapshot": lambda _metadata: {},
}


def _metadata_str(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _metadata_dict(metadata: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = metadata.get(key)
    if not isinstance(value, Mapping):
        return {}
    return _mapping_to_dict(cast(Mapping[Any, Any], value))


def _mapping_to_dict(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items()}


def _first_str(
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    *,
    key: str,
) -> str | None:
    first_value = _metadata_str(first, key)
    if first_value is not None:
        return first_value
    return _metadata_str(second, key)


__all__ = [
    "CeleryDeadLetterReplayPublisher",
    "DeadLetterReplayPublisher",
    "TASK_DEFAULT_QUEUES",
    "celery_kwargs_for_task",
]
