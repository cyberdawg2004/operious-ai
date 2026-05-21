"""Agent execution worker tasks."""

from __future__ import annotations

from typing import Any

from app.workers.celery_app import celery_app


@celery_app.task(
    name="execute_diagnostic_agent",
    bind=True,
    max_retries=3,
)
def execute_diagnostic_agent(
    self: Any,
    dispatch_id: str,
    session_id: str,
    tenant_id: str,
) -> dict[str, str]:
    """Async execution stub.

    Real DiagnosticAgent execution arrives in PR_W4.
    """
    return {
        "dispatch_id": dispatch_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "status": "queued",
    }


__all__ = ["execute_diagnostic_agent"]
