"""MVP-7 cross-channel identity detection — correctness and safety verification.

Five-test suite covering:
  Test 1 — True positive: same customer, cross-channel → MUST link (same customer_identity_id)
  Test 2 — True negative: different customers, different values → MUST NOT link
  Test 3 — False-positive guard (data-leak class): blank/None/whitespace/placeholder
             values must NEVER correlate two sessions even if they share the same
             absent/generic extracted value
  Test 4 — Normalization gap: same customer, different formatting → reports link/miss
  Test 5 — Tenant isolation: same identity value across two different tenants → MUST NOT link

Runs entirely in-process against InMemorySessionPersistence — no Bedrock, no DB, no
external services. Deterministic and fast.
"""

from __future__ import annotations

import uuid
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from typing import Any

import pytest

from app.cognition.extraction import ExtractionFieldSpec, ExtractionSchema
from app.session.enums import (
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import SessionId, SessionLineageId
from app.session.identity_resolution import (
    IdentityResolutionRuntime,
)
from app.session.persistence.memory import InMemorySessionPersistence
from app.session.persistence.records import SessionRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_A = "tenant-alpha"
_TENANT_B = "tenant-beta"


def _make_session_id() -> SessionId:
    return SessionId(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_record(
    *,
    session_id: SessionId | None = None,
    tenant_id: str = _TENANT_A,
    external_handle: str = "handle@example.com",
) -> SessionRecord:
    sid = session_id or _make_session_id()
    lineage_id = SessionLineageId(uuid.uuid4())
    now = _now()
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.OPERATIONAL_DOMAIN,
        external_handle=external_handle,
        tenant_id=tenant_id,
        principal_id=None,
        opened_at=now,
        lifecycle_phase=SessionLifecyclePhase.ACTIVE,
        lifecycle_recorded_at=now,
        lifecycle_reason=None,
        lineage_id=lineage_id,
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _extraction_schema_with_identity(*field_names: str) -> ExtractionSchema:
    """Build a schema where every listed field has identity_field=True."""
    return ExtractionSchema(
        fields=tuple(
            ExtractionFieldSpec(name=name, identity_field=True)
            for name in field_names
        )
    )


async def _record_and_resolve(
    *,
    persistence: InMemorySessionPersistence,
    session_id: str,
    tenant_id: str,
    extracted_fields: dict[str, Any],
    schema: ExtractionSchema,
) -> str | None:
    """Helper: record correlations for a session, then resolve its identity.

    Returns the customer_identity_id string or None.
    """
    runtime = IdentityResolutionRuntime(session_persistence=persistence)
    await runtime.record_identity_correlation(
        tenant_id=tenant_id,
        session_id=session_id,
        extracted_fields=extracted_fields,
        extraction_schema=schema,
    )
    result = await runtime.resolve(
        tenant_id=tenant_id,
        current_session_id=session_id,
        extracted_fields=extracted_fields,
        extraction_schema=schema,
    )
    return result.customer_identity_id


# ---------------------------------------------------------------------------
# Test 1 — True positive: same customer, cross-channel MUST link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_true_positive_same_customer_cross_channel_links() -> None:
    """
    SETUP: tenant-alpha has email, phone, serial_number as identity fields.
    Email ticket arrives: customer_email=alice@example.com
    WhatsApp ticket arrives later: same customer_email=alice@example.com

    MUST: both sessions resolve to the SAME customer_identity_id.
    MUST: correlation records exist linking both sessions via the email field.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email", "phone", "serial_number")

    # Session 1 — email channel
    sid1 = _make_session_id()
    await persistence.save_session(
        _session_record(
            session_id=sid1,
            tenant_id=_TENANT_A,
            external_handle="email:alice@example.com",
        )
    )

    # Session 2 — whatsapp channel (different external_handle, same identity value)
    sid2 = _make_session_id()
    await persistence.save_session(
        _session_record(
            session_id=sid2,
            tenant_id=_TENANT_A,
            external_handle="whatsapp:+15551234567",
        )
    )

    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    # Record correlations for session 1
    corrs1 = await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid1),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    assert len(corrs1) == 1, "session 1 must produce one correlation record for email"
    assert corrs1[0].annotation == "identity:email"

    # Session 2 comes in — resolves against session 1's stored correlation
    result2 = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid2),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )

    assert result2.match_stage == 2, (
        f"TEST 1 FAIL: expected Stage 2 match, got match_stage={result2.match_stage}"
    )
    assert result2.customer_identity_id is not None, "TEST 1 FAIL: customer_identity_id must not be None"
    assert result2.matched_session_ids, "TEST 1 FAIL: matched_session_ids must not be empty"
    assert str(sid1) in result2.matched_session_ids, (
        f"TEST 1 FAIL: session 1 ({sid1}) not in matched_session_ids {result2.matched_session_ids}"
    )
    assert result2.match_field == "email", (
        f"TEST 1 FAIL: expected match_field='email', got {result2.match_field!r}"
    )

    # Now record correlation for session 2 — both should derive the SAME identity id
    corrs2 = await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid2),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    assert len(corrs2) == 1

    result1_check = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid1),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    assert result1_check.customer_identity_id == result2.customer_identity_id, (
        f"TEST 1 FAIL: sessions must resolve to SAME customer_identity_id.\n"
        f"  session1 resolved to: {result1_check.customer_identity_id}\n"
        f"  session2 resolved to: {result2.customer_identity_id}"
    )


# ---------------------------------------------------------------------------
# Test 2 — True negative: different customers MUST NOT link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_true_negative_different_customers_do_not_link() -> None:
    """
    SETUP: two customers with DIFFERENT emails.
    Alice: alice@example.com
    Bob:   bob@example.com

    MUST: each resolves to a DIFFERENT customer_identity_id (or None on first ticket).
    MUST: neither session appears in the other's matched_session_ids.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email")

    sid_alice = _make_session_id()
    sid_bob = _make_session_id()

    await persistence.save_session(
        _session_record(session_id=sid_alice, external_handle="email:alice@example.com")
    )
    await persistence.save_session(
        _session_record(session_id=sid_bob, external_handle="email:bob@example.com")
    )

    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    # Record Alice's correlation
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid_alice),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )

    # Bob resolves — should get no match against Alice
    result_bob = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid_bob),
        extracted_fields={"email": "bob@example.com"},
        extraction_schema=schema,
    )

    assert result_bob.match_stage == 0, (
        f"TEST 2 FAIL: different customers must NOT match; got match_stage={result_bob.match_stage}"
    )
    assert result_bob.customer_identity_id is None, (
        f"TEST 2 FAIL: Bob got customer_identity_id={result_bob.customer_identity_id!r} — should be None"
    )
    assert str(sid_alice) not in result_bob.matched_session_ids, (
        "TEST 2 FAIL: Alice's session must not appear in Bob's matches"
    )

    # Record Bob's correlation, then verify Alice doesn't match Bob
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid_bob),
        extracted_fields={"email": "bob@example.com"},
        extraction_schema=schema,
    )
    result_alice_check = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid_alice),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    assert str(sid_bob) not in result_alice_check.matched_session_ids, (
        "TEST 2 FAIL: Bob's session must not appear in Alice's matches"
    )


# ---------------------------------------------------------------------------
# Test 3 — False-positive guard: blank/None/whitespace/placeholder must NOT link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_false_positive_guard_blank_values_never_correlate() -> None:
    """
    DATA-LEAK CLASS BUG TEST.

    Two DIFFERENT customers whose tickets produce blank or None identity values.
    The naive match: both have email=None (or empty string) → could be keyed as
    "customer_identity:email:" → same correlation key → WRONG LINK.

    The implementation must reject these before writing a correlation record,
    so blank/None/whitespace values produce ZERO correlation records and ZERO
    cross-session matches.

    Also tests whitespace-only strings and None.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email", "serial_number")
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    sid_c1 = _make_session_id()
    sid_c2 = _make_session_id()

    await persistence.save_session(
        _session_record(session_id=sid_c1, external_handle="ch1:customer1")
    )
    await persistence.save_session(
        _session_record(session_id=sid_c2, external_handle="ch2:customer2")
    )

    blank_variants: list[dict[str, Any]] = [
        {"email": None},
        {"email": ""},
        {"email": "   "},
        {"email": None, "serial_number": None},
        {},  # completely empty extraction
    ]

    for fields in blank_variants:
        corrs = await runtime.record_identity_correlation(
            tenant_id=_TENANT_A,
            session_id=str(sid_c1),
            extracted_fields=fields,
            extraction_schema=schema,
        )
        assert len(corrs) == 0, (
            f"TEST 3 FAIL (data-leak): record_identity_correlation produced "
            f"{len(corrs)} correlation record(s) for blank/None fields={fields!r}. "
            f"This would link different customers sharing an absent value."
        )

    # Now simulate customer 2 arriving — even if both produced blanks,
    # there must be NO correlation records in the store.
    all_blank_fields = {"email": None, "serial_number": ""}
    corrs2 = await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid_c2),
        extracted_fields=all_blank_fields,
        extraction_schema=schema,
    )
    assert len(corrs2) == 0, (
        "TEST 3 FAIL: customer 2 with blank fields must produce 0 correlations"
    )

    # Resolve customer 2 — must get NO match
    result_c2 = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid_c2),
        extracted_fields=all_blank_fields,
        extraction_schema=schema,
    )
    assert result_c2.match_stage == 0, (
        f"TEST 3 FAIL (data-leak): customer 2 with blank fields matched "
        f"match_stage={result_c2.match_stage} against customer 1. "
        f"customer_identity_id={result_c2.customer_identity_id!r}"
    )
    assert result_c2.customer_identity_id is None, (
        "TEST 3 FAIL (data-leak): blank-field resolution must return customer_identity_id=None"
    )
    assert str(sid_c1) not in result_c2.matched_session_ids, (
        "TEST 3 FAIL (data-leak): customer 2 must not be linked to customer 1 via blank value"
    )


@pytest.mark.asyncio
async def test_false_positive_guard_non_identity_fields_not_correlated() -> None:
    """Fields not marked identity_field=True must not be used as correlation keys,
    even if they contain values that would collide across customers."""
    persistence = InMemorySessionPersistence()
    # Only serial_number is an identity field; email is NOT
    schema = ExtractionSchema(
        fields=(
            ExtractionFieldSpec(name="email", identity_field=False),
            ExtractionFieldSpec(name="serial_number", identity_field=True),
        )
    )
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    sid1 = _make_session_id()
    sid2 = _make_session_id()
    await persistence.save_session(_session_record(session_id=sid1))
    await persistence.save_session(_session_record(session_id=sid2))

    # Both customers share the same email (common domain), different serials
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid1),
        extracted_fields={"email": "shared@company.com", "serial_number": "SN-AAA"},
        extraction_schema=schema,
    )
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid2),
        extracted_fields={"email": "shared@company.com", "serial_number": "SN-BBB"},
        extraction_schema=schema,
    )

    # Customer 2 resolving with same email but different serial — must NOT match customer 1
    result = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid2),
        extracted_fields={"email": "shared@company.com", "serial_number": "SN-BBB"},
        extraction_schema=schema,
    )
    assert str(sid1) not in result.matched_session_ids, (
        "TEST 3b FAIL: non-identity-field 'email' must not be used as correlation key"
    )


# ---------------------------------------------------------------------------
# Test 4 — Normalization gap (format variance reporting)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normalization_gap_case_sensitivity() -> None:
    """
    NORMALIZATION CHECK — email case variance.

    Same customer uses 'Alice@Example.COM' on channel 1 and 'alice@example.com' on channel 2.
    The current implementation does NOT normalize before matching (exact string match).

    Expected result: NO match (miss). This test documents the behavior:
    - If it PASSES (no match) → normalization gap confirmed; report to Imad.
    - If it somehow matches → unexpected; report that too.

    This is a known acceptable gap for v1 (documented, not a bug), but Imad should know.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email")
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    sid1 = _make_session_id()
    sid2 = _make_session_id()
    await persistence.save_session(_session_record(session_id=sid1))
    await persistence.save_session(_session_record(session_id=sid2))

    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid1),
        extracted_fields={"email": "Alice@Example.COM"},
        extraction_schema=schema,
    )

    result = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid2),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )

    # Document the actual behavior without asserting a specific outcome —
    # both outcomes need to be reported honestly.
    is_linked = result.match_stage > 0
    # We ASSERT it is NOT linked (documents current behavior = no normalization)
    assert not is_linked, (
        "NORMALIZATION NOTE: email case variant DID link — unexpected; "
        "verify this is intentional normalization, not accidental collision."
    )
    # This assertion serves as documentation: if it ever starts normalizing,
    # this test will fail and alert the team.


@pytest.mark.asyncio
async def test_normalization_gap_serial_formatting() -> None:
    """
    Serial number 'SN-12345' vs 'sn12345' — no normalization expected.
    Documents that format variants of the same serial will be missed.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("serial_number")
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    sid1 = _make_session_id()
    sid2 = _make_session_id()
    await persistence.save_session(_session_record(session_id=sid1))
    await persistence.save_session(_session_record(session_id=sid2))

    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid1),
        extracted_fields={"serial_number": "SN-12345"},
        extraction_schema=schema,
    )

    result = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid2),
        extracted_fields={"serial_number": "sn12345"},
        extraction_schema=schema,
    )

    # Documents current behavior: no normalization = miss
    assert result.match_stage == 0, (
        "NORMALIZATION CHANGE DETECTED: serial variant 'sn12345' now matches 'SN-12345'. "
        "Verify this is intentional normalization."
    )


# ---------------------------------------------------------------------------
# Test 5 — Tenant isolation: same identity value across tenants MUST NOT link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_same_value_different_tenants() -> None:
    """
    DATA-LEAK CLASS BUG TEST.

    Customer in tenant-alpha and customer in tenant-beta share the same email
    address. This is plausible: same person using two separate tenants' support
    portals, or a common corporate email that appears in multiple tenants' data.

    MUST: resolving from tenant-alpha must NEVER see tenant-beta's correlations.
    MUST: the customer_identity_id derived for tenant-alpha's session must NOT
          match what tenant-beta would resolve.
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email")
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    shared_email = "shared-user@example.com"

    sid_alpha = _make_session_id()
    sid_beta = _make_session_id()

    await persistence.save_session(
        _session_record(
            session_id=sid_alpha,
            tenant_id=_TENANT_A,
            external_handle="email:shared-user@example.com",
        )
    )
    await persistence.save_session(
        _session_record(
            session_id=sid_beta,
            tenant_id=_TENANT_B,
            external_handle="email:shared-user@example.com",
        )
    )

    # Record correlation for tenant-alpha
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid_alpha),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )

    # Tenant-beta second session resolves — must NOT see tenant-alpha's record
    sid_beta_2 = _make_session_id()
    await persistence.save_session(
        _session_record(
            session_id=sid_beta_2,
            tenant_id=_TENANT_B,
            external_handle="whatsapp:+15559999999",
        )
    )

    result_beta2 = await runtime.resolve(
        tenant_id=_TENANT_B,
        current_session_id=str(sid_beta_2),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )

    assert str(sid_alpha) not in result_beta2.matched_session_ids, (
        f"TEST 5 FAIL (cross-tenant data leak): tenant-beta resolved a session "
        f"from tenant-alpha via shared email {shared_email!r}. "
        f"matched_session_ids={result_beta2.matched_session_ids}"
    )

    # Also confirm match_stage == 0 for tenant-beta (no cross-tenant correlation)
    assert result_beta2.match_stage == 0, (
        f"TEST 5 FAIL (cross-tenant data leak): tenant-beta match_stage="
        f"{result_beta2.match_stage} against tenant-alpha's correlation records"
    )


@pytest.mark.asyncio
async def test_tenant_isolation_identity_ids_are_tenant_scoped() -> None:
    """
    The customer_identity_id is deterministically derived from tenant_id + match_key.
    Even if two tenants have a customer with the same email, their identity IDs
    must be DIFFERENT (the namespace includes tenant_id).
    """
    persistence = InMemorySessionPersistence()
    schema = _extraction_schema_with_identity("email")
    runtime = IdentityResolutionRuntime(session_persistence=persistence)

    shared_email = "same@email.com"

    sid_a = _make_session_id()
    sid_b = _make_session_id()
    await persistence.save_session(
        _session_record(session_id=sid_a, tenant_id=_TENANT_A)
    )
    await persistence.save_session(
        _session_record(session_id=sid_b, tenant_id=_TENANT_B)
    )

    await runtime.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid_a),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )
    await runtime.record_identity_correlation(
        tenant_id=_TENANT_B,
        session_id=str(sid_b),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )

    result_a = await runtime.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(_make_session_id()),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )
    result_b = await runtime.resolve(
        tenant_id=_TENANT_B,
        current_session_id=str(_make_session_id()),
        extracted_fields={"email": shared_email},
        extraction_schema=schema,
    )

    assert result_a.customer_identity_id != result_b.customer_identity_id, (
        f"TEST 5b FAIL: tenant-alpha and tenant-beta resolved to the SAME "
        f"customer_identity_id={result_a.customer_identity_id!r} for shared email. "
        f"Identity IDs must be tenant-scoped."
    )


# ---------------------------------------------------------------------------
# Test — worker helper: _extracted_fields_to_identity_dict
# ---------------------------------------------------------------------------


def test_extracted_fields_to_identity_dict_filters_blanks() -> None:
    """The worker-layer helper that converts ExtractedOrderFields to a plain dict
    must filter out None and empty values before passing to identity resolution."""
    from app.cognition.extraction import ExtractedOrderFields
    from app.workers.agent_tasks import _extracted_fields_to_identity_dict

    schema = _extraction_schema_with_identity("email", "phone", "serial_number")

    # Mix of present and absent values
    fields = ExtractedOrderFields.model_validate({
        "email": {"value": "alice@example.com", "confidence": "high", "source": "text"},
        "phone": {"value": None},
        "serial_number": {"value": "   ", "confidence": "low", "source": "text"},
    })

    result = _extracted_fields_to_identity_dict(fields, schema.identity_fields())

    assert "email" in result, "present email must be included"
    assert result["email"] == "alice@example.com"
    assert "phone" not in result, "None value must be excluded"
    assert "serial_number" not in result, "whitespace-only value must be excluded"


def test_extracted_fields_to_identity_dict_empty_schema() -> None:
    """No identity fields in schema → empty dict, no crash."""
    from app.cognition.extraction import ExtractedOrderFields
    from app.workers.agent_tasks import _extracted_fields_to_identity_dict

    schema = ExtractionSchema(
        fields=(ExtractionFieldSpec(name="order_id", identity_field=False),)
    )
    fields = ExtractedOrderFields.model_validate({
        "order_id": {"value": "ORD-999", "confidence": "high", "source": "text"},
    })

    result = _extracted_fields_to_identity_dict(fields, schema.identity_fields())
    assert result == {}, "no identity fields → empty dict"


# ---------------------------------------------------------------------------
# Test — determinism: same inputs always produce same customer_identity_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_identity_id_is_deterministic() -> None:
    """The customer_identity_id is a uuid5 derived from tenant_id + field + value.
    Two independent runs for the same tenant+field+value must produce identical IDs.
    This property is essential for idempotent stamping across retries."""
    schema = _extraction_schema_with_identity("email")

    # Run 1
    p1 = InMemorySessionPersistence()
    sid1a = _make_session_id()
    sid1b = _make_session_id()
    await p1.save_session(_session_record(session_id=sid1a))
    await p1.save_session(_session_record(session_id=sid1b))
    r1 = IdentityResolutionRuntime(session_persistence=p1)
    await r1.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid1a),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    res1 = await r1.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid1b),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )

    # Run 2 — fresh persistence, same values
    p2 = InMemorySessionPersistence()
    sid2a = _make_session_id()
    sid2b = _make_session_id()
    await p2.save_session(_session_record(session_id=sid2a))
    await p2.save_session(_session_record(session_id=sid2b))
    r2 = IdentityResolutionRuntime(session_persistence=p2)
    await r2.record_identity_correlation(
        tenant_id=_TENANT_A,
        session_id=str(sid2a),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )
    res2 = await r2.resolve(
        tenant_id=_TENANT_A,
        current_session_id=str(sid2b),
        extracted_fields={"email": "alice@example.com"},
        extraction_schema=schema,
    )

    assert res1.customer_identity_id == res2.customer_identity_id, (
        f"DETERMINISM FAIL: two independent runs for same tenant+email produced "
        f"different customer_identity_id:\n  run1={res1.customer_identity_id}\n  run2={res2.customer_identity_id}"
    )


# ---------------------------------------------------------------------------
# Test — stamp idempotency: _stamp_customer_identity_id does not overwrite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stamp_customer_identity_id_does_not_overwrite_existing() -> None:
    """If a session already has a customer_identity_id, _stamp must not overwrite it."""
    from app.workers.agent_tasks import _stamp_customer_identity_id

    persistence = InMemorySessionPersistence()
    sid = _make_session_id()
    existing_identity = uuid.uuid4()

    record_with_identity = dc_replace(
        _session_record(session_id=sid, tenant_id=_TENANT_A),
        customer_identity_id=existing_identity,
    )
    await persistence.save_session(record_with_identity)

    # Attempt to stamp a DIFFERENT identity
    different_identity = str(uuid.uuid4())
    await _stamp_customer_identity_id(
        session_repo=persistence,  # type: ignore[arg-type]
        session_id=str(sid),
        tenant_id=_TENANT_A,
        customer_identity_id=different_identity,
    )

    stored = await persistence.get_session(sid, expected_tenant_id=_TENANT_A)
    assert stored is not None
    assert stored.customer_identity_id == existing_identity, (
        f"IDEMPOTENCY FAIL: stamp overwrote existing customer_identity_id.\n"
        f"  original:  {existing_identity}\n"
        f"  after stamp: {stored.customer_identity_id}"
    )
