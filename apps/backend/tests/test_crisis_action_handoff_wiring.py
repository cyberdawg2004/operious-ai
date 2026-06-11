"""Hermetic regression guard: crisis action handoff uses a DURABLE publisher (#76).

Both invoker construction paths (the API action-approval orchestration and the
diagnostic worker orchestration) MUST wire a DeferredEscalationPublisher and
flush it after commit, so a crisis governance handoff is written to a durable,
recoverable escalation outbox row rather than a fire-and-forget Celery publish.

This is the always-on guard (no DB required); the Postgres durability test
proves the runtime behaviour (the outbox row is PENDING before flush).
"""

from __future__ import annotations

import inspect

from app.dependencies.services import build_action_approval_service
from app.workers import agent_tasks


def test_action_orchestration_path_wires_durable_publisher_and_flush() -> None:
    source = inspect.getsource(build_action_approval_service)
    assert "DeferredEscalationPublisher(" in source
    assert "escalation_publisher=deferred_escalation_publisher" in source
    assert "post_commit_flush=deferred_escalation_publisher.flush" in source


def test_worker_orchestration_path_wires_durable_publisher_and_flush() -> None:
    source = inspect.getsource(agent_tasks._action_orchestration_runtime)
    assert "DeferredEscalationPublisher(" in source
    assert "escalation_publisher=deferred_escalation_publisher" in source
    assert (
        "post_commit_flushes.append(deferred_escalation_publisher.flush)" in source
    )
