"""Fail-fast, test-only side-effect guards for the Northstar seed proofs.

Nothing in this module is imported by application code.  The guards are
deliberately broad: the seed's only permitted I/O is its already-established
loopback PostgreSQL connection.  Any attempt to cross a canonical Operious
side-effect boundary raises before it can publish, construct a provider, load a
credential, or contact a network destination.
"""

from __future__ import annotations

import socket
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from celery.app.task import Task
from kombu import Producer

BoundaryClassification = Literal[
    "RUNTIME_GUARD_INSTALLED",
    "STRUCTURALLY_ABSENT_AT_SCHEMA_0104",
    "NOT_APPLICABLE_WITH_EVIDENCE",
]


class UnexpectedNorthstarSideEffect(RuntimeError):
    """Raised immediately when guarded seed construction reaches a boundary."""


@dataclass(frozen=True, slots=True)
class BoundaryInventoryItem:
    category: str
    classification: BoundaryClassification
    evidence: str


BOUNDARY_INVENTORY: tuple[BoundaryInventoryItem, ...] = (
    BoundaryInventoryItem("Celery task publication", "RUNTIME_GUARD_INSTALLED", "Celery.send_task and Task delay/apply_async"),
    BoundaryInventoryItem("broker/event publication", "RUNTIME_GUARD_INSTALLED", "Kombu Producer.publish"),
    BoundaryInventoryItem("HTTP clients", "RUNTIME_GUARD_INSTALLED", "httpx request methods and Operious HTTP factories"),
    BoundaryInventoryItem("raw network connections", "RUNTIME_GUARD_INSTALLED", "socket connect and create_connection"),
    BoundaryInventoryItem("connector resolution", "RUNTIME_GUARD_INSTALLED", "TenantConnectorRegistry.resolve and action registry factory"),
    BoundaryInventoryItem("connector invocation", "RUNTIME_GUARD_INSTALLED", "GenericConnectorTool.invoke"),
    BoundaryInventoryItem("credential loading/decryption", "RUNTIME_GUARD_INSTALLED", "connector credential runtimes"),
    BoundaryInventoryItem("provider/client construction", "RUNTIME_GUARD_INSTALLED", "SES and WhatsApp sender constructors"),
    BoundaryInventoryItem("email/message delivery", "RUNTIME_GUARD_INSTALLED", "SES and WhatsApp sender methods"),
    BoundaryInventoryItem("outbound dispatch", "RUNTIME_GUARD_INSTALLED", "outbound-send outbox publisher"),
    BoundaryInventoryItem("webhook dispatch", "RUNTIME_GUARD_INSTALLED", "ingress-dispatch outbox publisher"),
    BoundaryInventoryItem("fulfillment/action execution", "RUNTIME_GUARD_INSTALLED", "generic connector invocation"),
    BoundaryInventoryItem("internal receipt executor", "RUNTIME_GUARD_INSTALLED", "InternalExecutionReceiptTool.invoke"),
    BoundaryInventoryItem("work-order publication", "RUNTIME_GUARD_INSTALLED", "PostgresWorkOrderRepository.create_work_order"),
    BoundaryInventoryItem("retry/reconciliation scheduling", "RUNTIME_GUARD_INSTALLED", "Task apply_async guard"),
    BoundaryInventoryItem("dead-letter publication", "RUNTIME_GUARD_INSTALLED", "Celery semantic quarantine publisher"),
    BoundaryInventoryItem("escalation publication", "RUNTIME_GUARD_INSTALLED", "Celery escalation publisher"),
)


def _empty_counts() -> dict[str, int]:
    return {}


@dataclass(slots=True)
class SideEffectGuard:
    """Records attempted boundaries; success requires every count to be zero."""

    counts: dict[str, int] = field(default_factory=_empty_counts)

    def block(self, boundary: str) -> None:
        self.counts[boundary] = self.counts.get(boundary, 0) + 1
        raise UnexpectedNorthstarSideEffect(boundary)

    @property
    def all_counts_zero(self) -> bool:
        return not self.counts


@contextmanager
def install_northstar_side_effect_guards(
    monkeypatch: Any,
) -> Generator[SideEffectGuard, None, None]:
    """Arm canonical side-effect boundaries for one real seed execution.

    The caller must establish the local test database connection before
    entering this context.  The socket guard then permits no new destination,
    making the existing connection the sole allowable I/O path.
    """

    guard = SideEffectGuard()

    def sync_block(boundary: str):
        def blocked(*_args: object, **_kwargs: object) -> object:
            guard.block(boundary)
        return blocked

    def async_block(boundary: str):
        async def blocked(*_args: object, **_kwargs: object) -> object:
            guard.block(boundary)
        return blocked

    # Transport and task boundaries.
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", sync_block("celery.send_task"))
    monkeypatch.setattr(Task, "delay", sync_block("celery.task.delay"))
    monkeypatch.setattr(Task, "apply_async", sync_block("celery.task.apply_async"))
    monkeypatch.setattr(Producer, "publish", sync_block("broker.producer.publish"))
    monkeypatch.setattr(httpx.AsyncClient, "request", async_block("http.async_client.request"))
    monkeypatch.setattr(httpx.Client, "request", sync_block("http.client.request"))
    monkeypatch.setattr(socket.socket, "connect", sync_block("network.socket.connect"))
    monkeypatch.setattr(socket, "create_connection", sync_block("network.create_connection"))

    # Project HTTP/client construction and connector/credential boundaries.
    from app.agents.tools.connectors.credentials import ConnectorScopedCredentialRuntime
    from app.agents.tools.connectors.generic import (
        ChannelBridgedConnectorCredentialRuntime,
        GenericConnectorTool,
    )
    from app.agents.tools.registry import TenantConnectorRegistry
    from app.boundary.outbound.email_ses import SesV2EmailSender
    from app.boundary.outbound.whatsapp import WhatsAppGraphSender
    from app.core import http as project_http

    monkeypatch.setattr(project_http, "init_shared_http_client", sync_block("http.init_shared_client"))
    monkeypatch.setattr(project_http, "get_shared_http_client", sync_block("http.get_shared_client"))
    monkeypatch.setattr(project_http, "create_isolated_http_client", sync_block("http.create_isolated_client"))
    monkeypatch.setattr(TenantConnectorRegistry, "resolve", async_block("connector.registry.resolve"))
    # Patch the module attribute so imported call sites cannot bypass the guard.
    import app.agents.tools.actions as action_tools

    monkeypatch.setattr(action_tools, "build_tenant_action_tool_registry", async_block("connector.registry.factory"))
    monkeypatch.setattr(GenericConnectorTool, "invoke", async_block("connector.invoke"))
    monkeypatch.setattr(ConnectorScopedCredentialRuntime, "load_connector_credentials", async_block("credential.connector.load"))
    monkeypatch.setattr(ChannelBridgedConnectorCredentialRuntime, "load_connector_credentials", async_block("credential.channel.load"))
    monkeypatch.setattr(SesV2EmailSender, "__init__", sync_block("provider.ses.construct"))
    monkeypatch.setattr(SesV2EmailSender, "send_email", async_block("delivery.email.send"))
    monkeypatch.setattr(WhatsAppGraphSender, "__init__", sync_block("provider.whatsapp.construct"))
    monkeypatch.setattr(WhatsAppGraphSender, "send_text_message", async_block("delivery.whatsapp.send"))

    # Operious publishers and work-order persistence are separate from the
    # seed's persistence graph and must never be reached during construction.
    from app.boundary import ingress_dispatch_publisher, outbound_send_publisher
    from app.escalation.celery_publisher import CeleryEscalationPublisher
    from app.semantic.quarantine_publisher import CelerySemanticQuarantinePublisher
    from app.work_orders.persistence.postgres import PostgresWorkOrderRepository

    monkeypatch.setattr(outbound_send_publisher, "enqueue_outbound_send_outbox", sync_block("outbound.dispatch"))
    monkeypatch.setattr(ingress_dispatch_publisher, "enqueue_ingress_dispatch_outbox", sync_block("webhook.dispatch"))
    monkeypatch.setattr(CeleryEscalationPublisher, "publish_governance_denial", async_block("escalation.publish_denial"))
    monkeypatch.setattr(CeleryEscalationPublisher, "publish_governance_escalation", async_block("escalation.publish"))
    monkeypatch.setattr(CelerySemanticQuarantinePublisher, "publish", sync_block("dead_letter.publish"))
    monkeypatch.setattr(PostgresWorkOrderRepository, "create_work_order", async_block("work_order.create"))

    try:
        yield guard
    finally:
        # monkeypatch rolls everything back as part of pytest's fixture scope.
        pass


__all__ = [
    "BOUNDARY_INVENTORY",
    "BoundaryInventoryItem",
    "SideEffectGuard",
    "UnexpectedNorthstarSideEffect",
    "install_northstar_side_effect_guards",
]
