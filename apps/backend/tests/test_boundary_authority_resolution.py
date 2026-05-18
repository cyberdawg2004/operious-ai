"""Phase 2.75-β regression tests — boundary AuthorityResolution.

Constitutional guarantees:

* Both boundary runtimes (ingress / egress) MUST resolve a tenant
  via ``request_authority_resolution`` at the orchestration entry
  rather than reading ``request.source.tenant_id`` directly.
* ``BoundaryTrace.tenant_authority_source`` MUST be stamped with
  the ``AuthoritySource`` value that yielded the effective
  ``tenant_id``.
* Typed ``AuthorityContext`` (Wedge B2) wins over
  ``BoundarySource.tenant_id`` when both are present — the inbound
  source-derived tenant is the OBSERVED axis only.
* Persisted records and trace metadata project the resolved
  ``tenant_id`` (not the legacy source-derived one).
* A static source-scan invariant guarantees neither runtime reads
  ``request.source.tenant_id`` outside the singular
  ``request_authority_resolution`` call site.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.boundary.adapters.builtin.zendesk import (
    ZendeskWebhookAdapter,
)
from app.boundary.contracts.requests import (
    BoundaryEgressRequest,
    BoundaryIngressRequest,
)
from app.boundary.egress.runtime import BoundaryEgressRuntime
from app.boundary.enums import BoundarySourceType
from app.boundary.idempotency.registry import (
    BoundaryIdempotencyRegistry,
)
from app.boundary.ingress.runtime import BoundaryIngressRuntime
from app.boundary.models.payload import (
    EgressPayload,
    IngressPayload,
)
from app.boundary.models.source import BoundarySource
from app.boundary.registry.registry import BoundaryAdapterRegistry
from app.identity import AuthorityContext, AuthoritySource


def _source(tenant: str | None = "tenant-source") -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.ZENDESK,
        source_id="acct-1",
        tenant_id=tenant,
    )


def _payload() -> IngressPayload:
    return IngressPayload(
        body={
            "event_id": "ze-evt-1",
            "ticket_id": "t-1",
            "type": "ticket.comment_created",
            "comment": {"body": "hi"},
            "created_at": "2026-01-01T00:00:00Z",
        }
    )


def _ingress_runtime() -> BoundaryIngressRuntime:
    return BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry([ZendeskWebhookAdapter()]),
        idempotency=BoundaryIdempotencyRegistry(),
    )


def _egress_runtime() -> BoundaryEgressRuntime:
    return BoundaryEgressRuntime(
        adapters=BoundaryAdapterRegistry([ZendeskWebhookAdapter()]),
    )


# ─── INGRESS — attribution axis ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ingress_typed_authority_wins_over_source_tenant() -> None:
    """Typed authority dominates inbound-source tenant.

    When the caller mints an ``AuthorityContext`` (the constitutional
    Wedge-B2 path), the resolved ``tenant_id`` MUST come from
    ``request.authority`` and the trace MUST record
    ``TYPED_AUTHORITY`` as the source.
    """
    rt = _ingress_runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="zendesk_webhook_adapter",
            payload=_payload(),
            authority=AuthorityContext(tenant_id="tenant-verified"),
        )
    )
    assert envelope.is_ok
    trace = envelope.trace
    assert trace.tenant_id == "tenant-verified"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )
    result = envelope.unwrap()
    assert result.tenant_id == "tenant-verified"


@pytest.mark.asyncio
async def test_ingress_observed_source_when_no_typed_authority() -> None:
    """Falls back to the inbound source tenant as OBSERVED axis."""
    rt = _ingress_runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="zendesk_webhook_adapter",
            payload=_payload(),
        )
    )
    assert envelope.is_ok
    trace = envelope.trace
    assert trace.tenant_id == "tenant-source"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.OBSERVED_TENANT.value
    )


@pytest.mark.asyncio
async def test_ingress_none_when_anonymous() -> None:
    """No authority anywhere → ``AuthoritySource.NONE``."""
    rt = _ingress_runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_source(tenant=None),
            adapter_name="zendesk_webhook_adapter",
            payload=_payload(),
        )
    )
    assert envelope.is_ok
    trace = envelope.trace
    assert trace.tenant_id is None
    assert (
        trace.tenant_authority_source
        == AuthoritySource.NONE.value
    )


@pytest.mark.asyncio
async def test_ingress_failed_envelope_stamps_authority_source() -> None:
    """Adapter-resolution failures still stamp the attribution axis."""
    rt = _ingress_runtime()
    envelope = await rt.ingest(
        BoundaryIngressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="does_not_exist",
            payload=_payload(),
            authority=AuthorityContext(tenant_id="tenant-verified"),
        )
    )
    assert envelope.result is None
    trace = envelope.trace
    assert trace.tenant_id == "tenant-verified"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


# ─── EGRESS — attribution axis ──────────────────────────────────────


@pytest.mark.asyncio
async def test_egress_typed_authority_wins_over_source_tenant() -> None:
    rt = _egress_runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="zendesk_webhook_adapter",
            artifact={"body": "ack"},
            prebuilt_payload=EgressPayload(body={"text": "ack"}),
            authority=AuthorityContext(tenant_id="tenant-verified"),
        )
    )
    assert envelope.is_ok
    trace = envelope.trace
    assert trace.tenant_id == "tenant-verified"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )
    result = envelope.unwrap()
    assert result.tenant_id == "tenant-verified"


@pytest.mark.asyncio
async def test_egress_observed_source_when_no_typed_authority() -> None:
    rt = _egress_runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="zendesk_webhook_adapter",
            artifact={"body": "ack"},
            prebuilt_payload=EgressPayload(body={"text": "ack"}),
        )
    )
    assert envelope.is_ok
    trace = envelope.trace
    assert trace.tenant_id == "tenant-source"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.OBSERVED_TENANT.value
    )


@pytest.mark.asyncio
async def test_egress_failed_envelope_stamps_authority_source() -> None:
    rt = _egress_runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(tenant="tenant-source"),
            adapter_name="does_not_exist",
            artifact={"body": "ack"},
            authority=AuthorityContext(tenant_id="tenant-verified"),
        )
    )
    assert envelope.result is None
    trace = envelope.trace
    assert trace.tenant_id == "tenant-verified"
    assert (
        trace.tenant_authority_source
        == AuthoritySource.TYPED_AUTHORITY.value
    )


# ─── Static source-scan invariants ──────────────────────────────────


_BOUNDARY_RUNTIMES = (
    Path(__file__).resolve().parent.parent
    / "app/boundary/ingress/runtime.py",
    Path(__file__).resolve().parent.parent
    / "app/boundary/egress/runtime.py",
)


def test_boundary_runtimes_call_request_authority_resolution() -> None:
    """The singular resolution call site must exist on entry."""
    for path in _BOUNDARY_RUNTIMES:
        text = path.read_text()
        assert "request_authority_resolution(" in text, (
            f"{path} missing request_authority_resolution call"
        )


def test_boundary_runtimes_never_read_source_tenant_directly() -> None:
    """``request.source.tenant_id`` must not leak into call paths.

    Constitutional rule (Wedge 2.75-β): the only legitimate read of
    ``request.source.tenant_id`` inside a boundary runtime is the
    one passed as ``observed_tenant_id=`` to
    ``request_authority_resolution``. Every other read is a
    tenant-coalescing regression.
    """
    for path in _BOUNDARY_RUNTIMES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if node.attr != "tenant_id":
                continue
            inner = node.value
            if not (
                isinstance(inner, ast.Attribute)
                and inner.attr == "source"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "request"
            ):
                continue
            parent_keyword = _enclosing_call_keyword(tree, node)
            assert parent_keyword == "observed_tenant_id", (
                f"{path}: forbidden read of "
                "request.source.tenant_id outside the singular "
                "request_authority_resolution(observed_tenant_id=...) "
                "call site"
            )


def _enclosing_call_keyword(
    tree: ast.AST, target: ast.AST
) -> str | None:
    """Find the immediate ``Call`` keyword whose value is ``target``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.value is target:
                return kw.arg
    return None
