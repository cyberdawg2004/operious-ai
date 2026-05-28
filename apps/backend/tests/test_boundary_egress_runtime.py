"""`BoundaryEgressRuntime` integration tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence.memory import InMemoryGovernanceRepository
from app.governance.persistence.records import GovernanceDecisionRecord


_ALLOW_DECISION_ID = uuid.UUID("5d8df9c5-57c4-5d34-86b4-1a52935d5141")
_DENY_DECISION_ID = uuid.UUID("ef5bfcf8-2be7-5b0d-9966-957408e6ef79")


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
    *,
    persistence: InMemoryBoundaryPersistence | None = None,
    governance_repository: InMemoryGovernanceRepository | None = None,
) -> BoundaryEgressRuntime:
    reg = BoundaryAdapterRegistry(
        [_SimpleEgressAdapter(), _RaisingEgressAdapter()]
    )
    return BoundaryEgressRuntime(
        adapters=reg,
        persistence=persistence,
        governance_repository=governance_repository,
    )


def _source() -> BoundarySource:
    return BoundarySource(
        source_type=BoundarySourceType.GENERIC,
        source_id="endpoint-1",
        tenant_id="tenant-1",
    )


async def _governance_repo(
    *,
    decision: Decision = Decision.ALLOW,
    decision_id: uuid.UUID = _ALLOW_DECISION_ID,
    tenant_id: str = "tenant-1",
) -> InMemoryGovernanceRepository:
    repo = InMemoryGovernanceRepository()
    await repo.record_decision(
        GovernanceDecisionRecord(
            decision_id=str(decision_id),
            decision=decision.value,
            stage=EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id="test-boundary-egress",
            reason="test fixture",
            decided_at=datetime(2026, 5, 29, tzinfo=timezone.utc).isoformat(),
            tenant_id=tenant_id,
            subject_kind="boundary.egress",
        )
    )
    return repo


# ─── Construction ───────────────────────────────────────────────────


def test_egress_runtime_exposes_dependencies() -> None:
    rt = _runtime()
    assert rt.runtime_instance_id is not None
    assert rt.persistence is None


# ─── Translation ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_translates_artifact() -> None:
    rt = _runtime(governance_repository=await _governance_repo())
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hello": "world"},
            governance_decision_id=_ALLOW_DECISION_ID,
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
    rt = _runtime(governance_repository=await _governance_repo())
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="any-name-allowed",
            artifact=None,
            governance_decision_id=_ALLOW_DECISION_ID,
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
    rt = _runtime(governance_repository=await _governance_repo())
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="missing",
            artifact={},
            governance_decision_id=_ALLOW_DECISION_ID,
        )
    )
    assert envelope.result is None
    assert envelope.error is not None


@pytest.mark.asyncio
async def test_emit_raising_adapter_does_not_kill_runtime() -> None:
    rt = _runtime(governance_repository=await _governance_repo())
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="raising_egress_adapter",
            artifact={},
            governance_decision_id=_ALLOW_DECISION_ID,
        )
    )
    # Result is produced; framework error captured.
    assert envelope.result is not None
    assert envelope.error is not None
    result = envelope.unwrap()
    assert result.payload is None
    assert result.error is not None


@pytest.mark.asyncio
async def test_emit_without_governance_decision_id_fails_closed() -> None:
    rt = _runtime(governance_repository=await _governance_repo())
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hi": True},
        )
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert "governance_decision_id" in str(envelope.error)


@pytest.mark.asyncio
async def test_emit_with_non_allow_governance_decision_fails_closed() -> None:
    rt = _runtime(
        governance_repository=await _governance_repo(
            decision=Decision.DENY,
            decision_id=_DENY_DECISION_ID,
        )
    )
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hi": True},
            governance_decision_id=_DENY_DECISION_ID,
        )
    )
    assert envelope.result is None
    assert envelope.error is not None
    assert "ALLOW" in str(envelope.error)


# ─── Persistence ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_egress_persistence_writes_record() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(
        persistence=store,
        governance_repository=await _governance_repo(),
    )
    envelope = await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"hi": True},
            governance_decision_id=_ALLOW_DECISION_ID,
        )
    )
    record = await store.get_egress(envelope.unwrap().egress_id)
    assert record is not None
    assert (
        record.payload_target_uri
        == "https://api.example/endpoint-1"
    )
    assert record.governance_decision_id == _ALLOW_DECISION_ID


@pytest.mark.asyncio
async def test_egress_listing_filters_by_correlation() -> None:
    store = InMemoryBoundaryPersistence()
    rt = _runtime(
        persistence=store,
        governance_repository=await _governance_repo(),
    )
    await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"a": 1},
            correlation_id="corr-A",
            governance_decision_id=_ALLOW_DECISION_ID,
        )
    )
    await rt.emit(
        BoundaryEgressRequest(
            source=_source(),
            adapter_name="simple_egress_adapter",
            artifact={"a": 2},
            correlation_id="corr-B",
            governance_decision_id=_ALLOW_DECISION_ID,
        )
    )
    page = await store.list_egress(
        BoundaryEgressQuery(correlation_id="corr-A")
    )
    assert page.total == 1
