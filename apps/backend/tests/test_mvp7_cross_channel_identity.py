"""MVP-7 — Cross-Channel Identity Resolution tests.

INVARIANT TESTS (per build plan):
1. Stage 1: same email handle on two tickets → context linked
2. Stage 2: different channel, same account_number (identity_field=true) → linked
3. Stage 3: CRM connector lookup returns prior session IDs → linked
4. No match: ticket proceeds normally, no error
5. Tenant scope: identity lookup cannot cross tenant boundaries
6. PII: CRM response fields not in identity_field config stripped before storage
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.cognition.extraction import ExtractionFieldSpec, ExtractionSchema
from app.session.enums import (
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionCorrelationId,
    SessionId,
    SessionLineageId,
)
from app.session.identity_resolution import (
    IDENTITY_CORRELATION_KIND,
    IDENTITY_CORRELATION_PREFIX,
    IdentityResolutionResult,
    IdentityResolutionRuntime,
    _derive_identity_id,
    _identity_correlation_key,
)
from app.session.persistence.models import (
    SessionCorrelationQuery,
    SessionQuery,
    SessionRecordPage,
)
from app.session.persistence.records import (
    SessionCorrelationRecord,
    SessionRecord,
)

_TENANT_A = "tenant-identity-a"
_TENANT_B = "tenant-identity-b"
_NOW = datetime.now(timezone.utc)


def _make_session(
    *,
    session_id: str | None = None,
    tenant_id: str = _TENANT_A,
    external_handle: str = "user@example.com",
) -> SessionRecord:
    sid = SessionId(uuid.UUID(session_id) if session_id else uuid.uuid4())
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle=external_handle,
        tenant_id=tenant_id,
        principal_id=None,
        opened_at=_NOW,
        lifecycle_phase=SessionLifecyclePhase.TERMINATED,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason=None,
        lineage_id=SessionLineageId(uuid.uuid4()),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
        context_environment=None,
        context_labels=(),
        context_attributes={},
        context_notes=None,
        metadata={},
    )


def _make_correlation(
    *,
    session_id: str,
    field_name: str,
    field_value: str,
    tenant_id: str = _TENANT_A,
) -> SessionCorrelationRecord:
    return SessionCorrelationRecord(
        correlation_id=SessionCorrelationId(uuid.uuid4()),
        session_id=SessionId(uuid.UUID(session_id)),
        kind=IDENTITY_CORRELATION_KIND,
        external_id=_identity_correlation_key(
            field_name=field_name, field_value=field_value
        ),
        recorded_at=_NOW,
        annotation=f"identity:{field_name}",
        attributes={
            "field_name": field_name,
            "field_value": field_value,
            "tenant_id": tenant_id,
        },
        metadata={"source": "identity_resolution"},
    )


def _identity_schema(
    *identity_fields: str,
    extra_fields: tuple[str, ...] = (),
) -> ExtractionSchema:
    """Build an extraction schema with the given identity fields."""
    specs = []
    for name in identity_fields:
        specs.append(ExtractionFieldSpec(name=name, identity_field=True))
    for name in extra_fields:
        specs.append(ExtractionFieldSpec(name=name, identity_field=False))
    return ExtractionSchema(fields=tuple(specs))


class _MockSessionPersistence:
    """In-memory session persistence for identity resolution tests."""

    def __init__(self) -> None:
        self.sessions: list[SessionRecord] = []
        self.correlations: list[SessionCorrelationRecord] = []
        self.saved_correlations: list[SessionCorrelationRecord] = []

    async def list_sessions(
        self,
        query: SessionQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        results = []
        for s in self.sessions:
            if expected_tenant_id and s.tenant_id != expected_tenant_id:
                continue
            if query.tenant_id and s.tenant_id != query.tenant_id:
                continue
            if query.external_handle and s.external_handle != query.external_handle:
                continue
            results.append(s)
        limit = query.limit or len(results)
        return SessionRecordPage(
            sessions=tuple(results[:limit]),
            total=len(results),
            limit=limit,
        )

    async def list_correlations(
        self,
        query: SessionCorrelationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecordPage:
        results = []
        for c in self.correlations:
            if query.kind and c.kind != query.kind:
                continue
            if query.external_id and c.external_id != query.external_id:
                continue
            if expected_tenant_id:
                if c.attributes.get("tenant_id") != expected_tenant_id:
                    continue
            results.append(c)
        limit = query.limit or len(results)
        return SessionRecordPage(
            correlations=tuple(results[:limit]),
            total=len(results),
            limit=limit,
        )

    async def save_correlation(self, record: SessionCorrelationRecord) -> None:
        self.saved_correlations.append(record)
        self.correlations.append(record)

    async def save_session(self, record: SessionRecord) -> SessionRecord:
        self.sessions.append(record)
        return record

    async def save_event(self, record: Any) -> None:
        pass

    async def get_session(
        self, session_id: SessionId, *, expected_tenant_id: str | None = None
    ) -> SessionRecord | None:
        for s in self.sessions:
            if s.session_id == session_id:
                if expected_tenant_id and s.tenant_id != expected_tenant_id:
                    return None
                return s
        return None

    async def get_event(self, event_id: Any, *, expected_tenant_id: str | None = None) -> None:
        return None

    async def get_event_by_idempotency_key(self, *, session_id: Any, idempotency_key: str, expected_tenant_id: str | None = None) -> None:
        return None

    async def get_correlation(self, correlation_id: Any, *, expected_tenant_id: str | None = None) -> None:
        return None

    async def list_events(self, query: Any, *, expected_tenant_id: str | None = None) -> SessionRecordPage:
        return SessionRecordPage(total=0, limit=0)


class TestStage1HandleMatch:
    """Stage 1: same handle on two tickets → context linked."""

    @pytest.mark.asyncio
    async def test_same_email_handle_links_sessions(self) -> None:
        persistence = _MockSessionPersistence()
        prior_session = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="user@example.com",
        )
        persistence.sessions.append(prior_session)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        current_session_id = str(uuid.uuid4())

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=current_session_id,
            external_handle="user@example.com",
        )

        assert result.match_stage == 1
        assert result.match_confidence == 1.0
        assert str(prior_session.session_id) in result.matched_session_ids
        assert result.customer_identity_id is not None
        assert result.match_field == "external_handle"

    @pytest.mark.asyncio
    async def test_same_phone_handle_links_sessions(self) -> None:
        persistence = _MockSessionPersistence()
        prior = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="+14155551234",
        )
        persistence.sessions.append(prior)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        current_id = str(uuid.uuid4())

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=current_id,
            external_handle="+14155551234",
        )

        assert result.match_stage == 1
        assert str(prior.session_id) in result.matched_session_ids

    @pytest.mark.asyncio
    async def test_same_whatsapp_handle_links_sessions(self) -> None:
        persistence = _MockSessionPersistence()
        prior = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="wa:14155551234",
        )
        persistence.sessions.append(prior)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="wa:14155551234",
        )

        assert result.match_stage == 1
        assert result.has_context()

    @pytest.mark.asyncio
    async def test_excludes_current_session_from_matches(self) -> None:
        persistence = _MockSessionPersistence()
        session_id = str(uuid.uuid4())
        current = _make_session(
            session_id=session_id,
            external_handle="user@example.com",
        )
        persistence.sessions.append(current)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=session_id,
            external_handle="user@example.com",
        )

        assert result.match_stage == 0
        assert not result.has_context()

    @pytest.mark.asyncio
    async def test_multiple_prior_sessions_all_returned(self) -> None:
        persistence = _MockSessionPersistence()
        for _ in range(5):
            persistence.sessions.append(
                _make_session(
                    session_id=str(uuid.uuid4()),
                    external_handle="repeat@customer.com",
                )
            )

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="repeat@customer.com",
        )

        assert result.match_stage == 1
        assert len(result.matched_session_ids) == 5


class TestStage2ExtractedFieldMatch:
    """Stage 2: different channel, same identity field → linked."""

    @pytest.mark.asyncio
    async def test_same_account_number_links_across_channels(self) -> None:
        persistence = _MockSessionPersistence()
        prior_session_id = str(uuid.uuid4())
        persistence.correlations.append(
            _make_correlation(
                session_id=prior_session_id,
                field_name="account_number",
                field_value="ACC-12345",
            )
        )

        schema = _identity_schema("account_number")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="different_handle@email.com",
            extracted_fields={"account_number": "ACC-12345"},
            extraction_schema=schema,
        )

        assert result.match_stage == 2
        assert result.match_confidence == 0.95
        assert prior_session_id in result.matched_session_ids
        assert result.match_field == "account_number"

    @pytest.mark.asyncio
    async def test_same_email_identity_field_links(self) -> None:
        persistence = _MockSessionPersistence()
        prior_id = str(uuid.uuid4())
        persistence.correlations.append(
            _make_correlation(
                session_id=prior_id,
                field_name="customer_email",
                field_value="alice@corp.com",
            )
        )

        schema = _identity_schema("customer_email", "phone")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="wa:different_channel",
            extracted_fields={
                "customer_email": "alice@corp.com",
                "phone": "+1234",
            },
            extraction_schema=schema,
        )

        assert result.match_stage == 2
        assert prior_id in result.matched_session_ids
        assert result.match_field == "customer_email"

    @pytest.mark.asyncio
    async def test_stage2_skipped_when_no_identity_fields(self) -> None:
        persistence = _MockSessionPersistence()
        schema = ExtractionSchema(
            fields=(
                ExtractionFieldSpec(name="order_id", identity_field=False),
            )
        )
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="no_match@test.com",
            extracted_fields={"order_id": "ORD-999"},
            extraction_schema=schema,
        )

        assert result.match_stage == 0

    @pytest.mark.asyncio
    async def test_stage2_skipped_when_identity_field_empty(self) -> None:
        persistence = _MockSessionPersistence()
        schema = _identity_schema("account_number")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="no_match@test.com",
            extracted_fields={"account_number": ""},
            extraction_schema=schema,
        )

        assert result.match_stage == 0

    @pytest.mark.asyncio
    async def test_stage2_excludes_current_session(self) -> None:
        persistence = _MockSessionPersistence()
        current_id = str(uuid.uuid4())
        persistence.correlations.append(
            _make_correlation(
                session_id=current_id,
                field_name="account_number",
                field_value="SELF",
            )
        )

        schema = _identity_schema("account_number")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=current_id,
            external_handle="new_channel",
            extracted_fields={"account_number": "SELF"},
            extraction_schema=schema,
        )

        assert result.match_stage == 0
        assert not result.has_context()


class TestNoMatch:
    """No match: ticket proceeds normally, no error."""

    @pytest.mark.asyncio
    async def test_no_sessions_returns_stage_zero(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="unknown@test.com",
        )

        assert result.match_stage == 0
        assert result.customer_identity_id is None
        assert result.matched_session_ids == ()
        assert not result.has_context()

    @pytest.mark.asyncio
    async def test_no_handle_no_fields_returns_stage_zero(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
        )

        assert result.match_stage == 0
        assert not result.has_context()

    @pytest.mark.asyncio
    async def test_persistence_error_returns_stage_zero(self) -> None:
        """NEVER fails — graceful degradation on any exception."""
        persistence = AsyncMock()
        persistence.list_sessions = AsyncMock(side_effect=RuntimeError("DB down"))

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="user@test.com",
        )

        assert result.match_stage == 0
        assert not result.has_context()


class TestTenantIsolation:
    """INVARIANT: identity lookup cannot cross tenant boundaries."""

    @pytest.mark.asyncio
    async def test_handle_match_scoped_to_tenant(self) -> None:
        persistence = _MockSessionPersistence()
        # Session belongs to tenant B
        other_tenant_session = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="shared@user.com",
            tenant_id=_TENANT_B,
        )
        persistence.sessions.append(other_tenant_session)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        # Resolve as tenant A — must NOT see tenant B's session
        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="shared@user.com",
        )

        assert result.match_stage == 0
        assert not result.has_context()

    @pytest.mark.asyncio
    async def test_correlation_match_scoped_to_tenant(self) -> None:
        persistence = _MockSessionPersistence()
        # Correlation belongs to tenant B
        persistence.correlations.append(
            _make_correlation(
                session_id=str(uuid.uuid4()),
                field_name="account_number",
                field_value="ACC-CROSS",
                tenant_id=_TENANT_B,
            )
        )

        schema = _identity_schema("account_number")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        # Resolve as tenant A — must NOT see tenant B's correlation
        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="new@test.com",
            extracted_fields={"account_number": "ACC-CROSS"},
            extraction_schema=schema,
        )

        assert result.match_stage == 0
        assert not result.has_context()

    @pytest.mark.asyncio
    async def test_same_tenant_matches_correctly(self) -> None:
        persistence = _MockSessionPersistence()
        same_tenant_session = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="same@user.com",
            tenant_id=_TENANT_A,
        )
        persistence.sessions.append(same_tenant_session)

        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="same@user.com",
        )

        assert result.match_stage == 1
        assert result.has_context()


class TestCascadeOrder:
    """Verifies the 3-stage cascade runs in order and stops at first match."""

    @pytest.mark.asyncio
    async def test_stage1_takes_priority_over_stage2(self) -> None:
        persistence = _MockSessionPersistence()
        handle_session = _make_session(
            session_id=str(uuid.uuid4()),
            external_handle="priority@test.com",
        )
        persistence.sessions.append(handle_session)

        # Also add a correlation that would match stage 2
        persistence.correlations.append(
            _make_correlation(
                session_id=str(uuid.uuid4()),
                field_name="account_number",
                field_value="ACC-PRIORITY",
            )
        )

        schema = _identity_schema("account_number")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="priority@test.com",
            extracted_fields={"account_number": "ACC-PRIORITY"},
            extraction_schema=schema,
        )

        # Stage 1 wins even though stage 2 also has a match
        assert result.match_stage == 1
        assert result.match_field == "external_handle"

    @pytest.mark.asyncio
    async def test_stage2_runs_when_stage1_misses(self) -> None:
        persistence = _MockSessionPersistence()
        # No sessions matching the handle
        # But a correlation matching the identity field
        persistence.correlations.append(
            _make_correlation(
                session_id=str(uuid.uuid4()),
                field_name="customer_id",
                field_value="CUST-789",
            )
        )

        schema = _identity_schema("customer_id")
        runtime = IdentityResolutionRuntime(session_persistence=persistence)

        result = await runtime.resolve(
            tenant_id=_TENANT_A,
            current_session_id=str(uuid.uuid4()),
            external_handle="no_match@test.com",
            extracted_fields={"customer_id": "CUST-789"},
            extraction_schema=schema,
        )

        assert result.match_stage == 2
        assert result.match_field == "customer_id"


class TestRecordIdentityCorrelation:
    """Tests for recording identity correlations after extraction."""

    @pytest.mark.asyncio
    async def test_records_correlation_for_identity_fields(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("account_number", "customer_email")

        session_id = str(uuid.uuid4())
        records = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=session_id,
            extracted_fields={
                "account_number": "ACC-123",
                "customer_email": "user@test.com",
            },
            extraction_schema=schema,
        )

        assert len(records) == 2
        assert len(persistence.saved_correlations) == 2

        external_ids = {r.external_id for r in records}
        assert f"{IDENTITY_CORRELATION_PREFIX}account_number:ACC-123" in external_ids
        assert f"{IDENTITY_CORRELATION_PREFIX}customer_email:user@test.com" in external_ids

    @pytest.mark.asyncio
    async def test_skips_empty_identity_fields(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("account_number", "phone")

        records = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={
                "account_number": "ACC-123",
                "phone": "",  # empty — should be skipped
            },
            extraction_schema=schema,
        )

        assert len(records) == 1
        assert records[0].external_id == f"{IDENTITY_CORRELATION_PREFIX}account_number:ACC-123"

    @pytest.mark.asyncio
    async def test_skips_non_identity_fields(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("account_number", extra_fields=("order_id",))

        records = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={
                "account_number": "ACC-123",
                "order_id": "ORD-456",  # not identity — skipped
            },
            extraction_schema=schema,
        )

        assert len(records) == 1

    @pytest.mark.asyncio
    async def test_no_records_when_no_identity_fields_in_schema(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = ExtractionSchema(
            fields=(ExtractionFieldSpec(name="order_id", identity_field=False),)
        )

        records = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={"order_id": "ORD-999"},
            extraction_schema=schema,
        )

        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_correlation_survives_partial_failure(self) -> None:
        """If one field fails to save, others still succeed."""
        persistence = _MockSessionPersistence()
        call_count = 0
        original_save = persistence.save_correlation

        async def _failing_save(record: SessionCorrelationRecord) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated failure")
            await original_save(record)

        persistence.save_correlation = _failing_save  # type: ignore[assignment]

        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("field_a", "field_b")

        records = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={"field_a": "val_a", "field_b": "val_b"},
            extraction_schema=schema,
        )

        # First fails, second succeeds
        assert len(records) == 1


class TestIdentityResolutionResult:
    """Tests for the IdentityResolutionResult data model."""

    def test_to_dict_roundtrip(self) -> None:
        result = IdentityResolutionResult(
            customer_identity_id="cust-123",
            matched_session_ids=("s1", "s2", "s3"),
            match_stage=2,
            match_confidence=0.95,
            match_field="account_number",
            metadata={"field_name": "account_number", "field_value": "ACC-1"},
        )
        d = result.to_dict()
        restored = IdentityResolutionResult.from_dict(d)
        assert restored.customer_identity_id == result.customer_identity_id
        assert restored.matched_session_ids == result.matched_session_ids
        assert restored.match_stage == result.match_stage
        assert restored.match_confidence == result.match_confidence
        assert restored.match_field == result.match_field
        assert restored.metadata == result.metadata

    def test_from_dict_minimal(self) -> None:
        data: dict[str, Any] = {}
        result = IdentityResolutionResult.from_dict(data)
        assert result.customer_identity_id is None
        assert result.matched_session_ids == ()
        assert result.match_stage == 0
        assert result.match_confidence == 0.0

    def test_has_context_true_when_matched(self) -> None:
        result = IdentityResolutionResult(
            matched_session_ids=("s1",),
            match_stage=1,
        )
        assert result.has_context() is True

    def test_has_context_false_when_no_match(self) -> None:
        result = IdentityResolutionResult()
        assert result.has_context() is False

    def test_has_context_false_when_stage_zero(self) -> None:
        result = IdentityResolutionResult(
            matched_session_ids=("s1",),
            match_stage=0,
        )
        assert result.has_context() is False


class TestDeterministicIdentityIds:
    """Identity IDs are deterministic (UUID5-based)."""

    def test_same_inputs_produce_same_identity_id(self) -> None:
        id1 = _derive_identity_id(tenant_id="t1", match_key="handle:user@x.com")
        id2 = _derive_identity_id(tenant_id="t1", match_key="handle:user@x.com")
        assert id1 == id2

    def test_different_tenants_produce_different_ids(self) -> None:
        id1 = _derive_identity_id(tenant_id="t1", match_key="handle:user@x.com")
        id2 = _derive_identity_id(tenant_id="t2", match_key="handle:user@x.com")
        assert id1 != id2

    def test_different_keys_produce_different_ids(self) -> None:
        id1 = _derive_identity_id(tenant_id="t1", match_key="handle:a@x.com")
        id2 = _derive_identity_id(tenant_id="t1", match_key="handle:b@x.com")
        assert id1 != id2


class TestPIIBoundary:
    """PII: Only identity_field values stored in correlations, not raw CRM data."""

    @pytest.mark.asyncio
    async def test_only_identity_fields_recorded_as_correlations(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("account_number", extra_fields=("full_name", "address"))

        await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={
                "account_number": "ACC-SECRET",
                "full_name": "John Doe",  # NOT identity — must NOT be stored
                "address": "123 Main St",  # NOT identity — must NOT be stored
            },
            extraction_schema=schema,
        )

        assert len(persistence.saved_correlations) == 1
        saved = persistence.saved_correlations[0]
        assert "ACC-SECRET" in saved.external_id
        assert "John Doe" not in saved.external_id
        assert "123 Main St" not in saved.external_id

    @pytest.mark.asyncio
    async def test_correlation_attributes_contain_only_field_metadata(self) -> None:
        persistence = _MockSessionPersistence()
        runtime = IdentityResolutionRuntime(session_persistence=persistence)
        schema = _identity_schema("customer_email")

        await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(uuid.uuid4()),
            extracted_fields={"customer_email": "pii@test.com"},
            extraction_schema=schema,
        )

        saved = persistence.saved_correlations[0]
        # Only the identity field name+value in attributes (required for matching)
        assert saved.attributes["field_name"] == "customer_email"
        assert saved.attributes["field_value"] == "pii@test.com"
        assert saved.attributes["tenant_id"] == _TENANT_A
