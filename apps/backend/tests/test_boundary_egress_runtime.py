"""`BoundaryEgressRuntime` integration tests."""

from __future__ import annotations

import pytest

from app.boundary.adapters.base import BaseEgressAdapter
from app.boundary.contracts.requests import (
    BoundaryEgressRequest,
)
from app.boundary.egress.runtime import BoundaryEgressRuntime
from app.boundary.enums import (
    BoundaryDirection,
    BoundarySourceType,
)
from app.boundary.models.payload import EgressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence.memory import (
    InMemoryBoundaryPersistence,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
)
from app.boundary.registry.registry import (
    BoundaryAdapterRegistry,
)


class _SimpleEgressAdapter(BaseEgressAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="simple_egress_adapter",
            source_type=BoundarySourceType.GENERIC,
        )

    def serialize(self, *, source, artifact):  # type: ignore[no-untyped-def]
        return EgressPayload(
            body={"echo": artifact},
            content_type="application/json",
            target_uri=f"https://api.example/{source.source_id}",
            method="POST",
            headers={"x-trace": "1"},
        )


class _RaisingEgressAdapter(BaseEgressAdapter):
    def __init__(self) -> None:
        super().__init__(
            name="raising_egress_adapter",
            source_type=BoundarySourceType.GENERIC,
        )

    def serialize(self, *, source, artifact):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


def _runtime(
    *, persistence: InMemoryBoundaryPersistence | None = None
) -> BoundaryEgressRuntime:
    reg = BoundaryAdapterRegistry(
        [_SimpleEgressAdapter(), _RaisingEgressAdapter()]
    )
    return BoundaryEgressRuntime(
        adapters=reg, persistence=persistence
    )


def _source() -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.GENERIC,
        source_id="endpoint-1",
        tenant_id="tenant-1",
    )


# ─── Construction ───────────────────────────────────────────────────


def test_egress_runtime_exposes_dependencies() -> None:
    rt = _runtime()
    assert rt.runtime_instance_id is not None
    assert rt.persistence is None


# ─── Translation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_translates_artifact() -> None:
    rt = _runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hello": "world"},
        )
    )
    assert envelope.is_ok
    result = envelope.unwrap()
    assert result.is_translated
    assert result.payload is not None
    assert result.payload.body == {"echo": {"hello": "world"}}
    assert result.direction is BoundaryDirection.EGRESS


@pytest.mark.asyncio
async def test_emit_with_prebuilt_payload_skips_adapter() -> None:
    rt = _runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="any-name-allowed",
            artifact=None,
            prebuilt_payload=EgressPayload(
                body={"prebuilt": True},
                target_uri="https://x",
            ),
        )
    )
    result = envelope.unwrap()
    assert result.payload is not None
    assert result.payload.body == {"prebuilt": True}


# ─── Failure paths ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_unknown_adapter_yields_failed_envelope() -> None:
    rt = _runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="missing",
            artifact={},
        )
    )
    assert envelope.result is None
    assert envelope.error is not None


@pytest.mark.asyncio
async def test_emit_raising_adapter_does_not_kill_runtime() -> None:
    rt = _runtime()
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="raising_egress_adapter",
            artifact={},
        )
    )
    # Result is produced; framework error captured.
    assert envelope.result is not None
    assert envelope.error is not None
    result = envelope.unwrap()
    assert result.payload is None
    assert result.error is not None


# ─── Persistence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_egress_persistence_writes_record() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(persistence=store)
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hi": True},
        )
    )
    record = await store.get_egress(envelope.unwrap().egress_id)
    assert record is not None
    assert (
        record.payload_target_uri
        == "https://api.example/endpoint-1"
    )


@pytest.mark.asyncio
async def test_egress_listing_filters_by_correlation() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(persistence=store)
    await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"a": 1},
            correlation_id="corr-A",
        )
    )
    await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"a": 2},
            correlation_id="corr-B",
        )
    )
    page = await store.list_egress(
        BoundaryEgressQuery(correlation_id="corr-A")
    )
    assert page.total == 1
