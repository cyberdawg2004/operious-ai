"""W1 break-controls: warranty_refund_rules tenant policy parsing + resolution.

Pure parser/resolve tests run with no Postgres (InMemoryTenantConfiguration
Repository, mirroring test_resolution_taxonomy_policy.py's pattern exactly).
The dual-control propose/approve/apply wiring at the bottom needs Postgres
(the change-request ledger has no in-memory implementation) and is gated
accordingly.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import PostgresOperationalEventPersistence
from app.events.appender import OperationalEventAppender
from app.runtime.warranty_refund_policy import (
    WARRANTY_REFUND_RULES_POLICY_TYPE,
    WarrantyRefundPolicyParseError,
    parse_warranty_refund_policy,
    resolve_warranty_refund_policy,
    validate_warranty_refund_policy_parameters,
)
from app.services.tenant_config_change_request_service import (
    TenantConfigChangeRequestService,
)
from app.services.tenant_configuration_service import TenantConfigurationService
from app.tenant.change_requests import (
    PostgresTenantConfigChangeRequestRepository,
    TenantConfigChangeRequestLifecycleError,
    TenantConfigChangeType,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    PostgresTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-warranty-refund-policy"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_APPROVED_BY = "policy-admin"
_APPROVAL_ID = "approval-warranty-refund-rules"
_MASTER_KEY = "w1-warranty-refund-master-key-32-bytes-min"


def _valid_parameters() -> dict[str, object]:
    return {
        "warranty_window_days": 730,
        "authorized_resellers": ["amazon.com", "official-store.com"],
        "required_evidence_by_claim_type": {
            "defective": ["order_id", "purchase_date", "seller"],
        },
        "remedy_sequence_by_claim_type": {
            "defective": ["replacement", "refurbished", "refund"],
        },
    }


def _record(
    *,
    parameters: dict[str, object],
    tenant_id: str = TENANT_ID,
    version: int = 1,
) -> TenantGovernancePolicyRecord:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
    return TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


# ─── parser ────────────────────────────────────────────────────────────────


def test_parse_valid_parameters() -> None:
    policy = parse_warranty_refund_policy(_record(parameters=_valid_parameters()))

    assert policy.warranty_window_days == 730
    assert policy.authorized_resellers == frozenset({"amazon.com", "official-store.com"})
    assert policy.required_evidence_for("defective") == (
        "order_id",
        "purchase_date",
        "seller",
    )
    assert policy.remedy_sequence_by_claim_type["defective"] == (
        "replacement",
        "refurbished",
        "refund",
    )


def test_authorized_resellers_normalized_lowercase() -> None:
    parameters = _valid_parameters()
    parameters["authorized_resellers"] = ["Amazon.COM", "  Official-Store.com  "]
    policy = parse_warranty_refund_policy(_record(parameters=parameters))

    assert policy.authorized_resellers == frozenset({"amazon.com", "official-store.com"})


def _drop_warranty_window_days(p: dict[str, object]) -> None:
    del p["warranty_window_days"]


def _zero_warranty_window_days(p: dict[str, object]) -> None:
    p["warranty_window_days"] = 0


def _negative_warranty_window_days(p: dict[str, object]) -> None:
    p["warranty_window_days"] = -5


def _string_warranty_window_days(p: dict[str, object]) -> None:
    p["warranty_window_days"] = "730"


def _drop_authorized_resellers(p: dict[str, object]) -> None:
    del p["authorized_resellers"]


def _empty_authorized_resellers(p: dict[str, object]) -> None:
    p["authorized_resellers"] = []


def _drop_required_evidence(p: dict[str, object]) -> None:
    del p["required_evidence_by_claim_type"]


def _empty_required_evidence(p: dict[str, object]) -> None:
    p["required_evidence_by_claim_type"] = {}


def _unknown_evidence_field(p: dict[str, object]) -> None:
    p["required_evidence_by_claim_type"] = {"defective": ["not_a_real_field"]}


@pytest.mark.parametrize(
    "mutate",
    [
        _drop_warranty_window_days,
        _zero_warranty_window_days,
        _negative_warranty_window_days,
        _string_warranty_window_days,
        _drop_authorized_resellers,
        _empty_authorized_resellers,
        _drop_required_evidence,
        _empty_required_evidence,
        _unknown_evidence_field,
    ],
)
def test_rejects_malformed_parameters(
    mutate: Callable[[dict[str, object]], None],
) -> None:
    parameters = _valid_parameters()
    mutate(parameters)
    with pytest.raises(WarrantyRefundPolicyParseError):
        validate_warranty_refund_policy_parameters(parameters)


def test_remedy_sequence_for_unknown_claim_type_rejected() -> None:
    parameters = _valid_parameters()
    parameters["remedy_sequence_by_claim_type"] = {
        "orphaned_claim_type": ["refund"],
    }
    with pytest.raises(WarrantyRefundPolicyParseError):
        validate_warranty_refund_policy_parameters(parameters)


def test_remedy_sequence_is_optional() -> None:
    parameters = _valid_parameters()
    del parameters["remedy_sequence_by_claim_type"]
    policy = parse_warranty_refund_policy(_record(parameters=parameters))
    assert policy.remedy_sequence_by_claim_type == {}


# ─── resolve (fail-closed to None, not an empty-but-vacuous policy) ───────


@pytest.mark.asyncio
async def test_resolve_with_no_repository_returns_none() -> None:
    policy = await resolve_warranty_refund_policy(
        repository=None,
        tenant_id=TENANT_ID,
    )
    assert policy is None


@pytest.mark.asyncio
async def test_resolve_with_no_active_record_returns_none() -> None:
    repository = InMemoryTenantConfigurationRepository()

    policy = await resolve_warranty_refund_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )
    assert policy is None


@pytest.mark.asyncio
async def test_resolve_with_valid_active_record_returns_parsed_policy() -> None:
    repository = InMemoryTenantConfigurationRepository()
    await repository.save_governance_policy(
        _record(parameters=_valid_parameters()), expected_tenant_id=TENANT_ID
    )

    policy = await resolve_warranty_refund_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )
    assert policy is not None
    assert policy.warranty_window_days == 730


@pytest.mark.asyncio
async def test_resolve_with_invalid_active_record_returns_none() -> None:
    """The deliberate divergence from resolution_taxonomy's fail-closed-to-
    empty pattern: an invalid/unparseable policy must resolve to None, not
    an empty-but-truthy policy that could vacuously pass every check."""
    repository = InMemoryTenantConfigurationRepository()
    await repository.save_governance_policy(
        _record(parameters={"warranty_window_days": -1}),
        expected_tenant_id=TENANT_ID,
    )

    policy = await resolve_warranty_refund_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )
    assert policy is None


@pytest.mark.asyncio
async def test_resolve_is_tenant_scoped_not_cross_tenant_visible() -> None:
    """Tenant A's warranty rules must never be evaluated for tenant B.

    A bank-tenant-style policy with a 60-day dispute window is saved for
    tenant A only. Resolving for tenant B (which has no policy of its
    own) must see nothing — not tenant A's, not a permissive default.
    """
    tenant_a = "tenant-warranty-refund-policy-a"
    tenant_b = "tenant-warranty-refund-policy-b"
    repository = InMemoryTenantConfigurationRepository()
    await repository.save_governance_policy(
        _record(
            parameters={
                "warranty_window_days": 60,
                "authorized_resellers": ["chase.com"],
                "required_evidence_by_claim_type": {
                    "disputed_transaction": ["purchase_date", "amount"],
                },
                "remedy_sequence_by_claim_type": {},
            },
            tenant_id=tenant_a,
        ),
        expected_tenant_id=tenant_a,
    )

    policy_for_a = await resolve_warranty_refund_policy(
        repository=repository, tenant_id=tenant_a
    )
    policy_for_b = await resolve_warranty_refund_policy(
        repository=repository, tenant_id=tenant_b
    )

    assert policy_for_a is not None
    assert policy_for_a.warranty_window_days == 60
    assert policy_for_b is None


# ─── dual-control propose/approve/apply (Postgres — no in-memory ledger) ──

_LEDGER_MASTER_KEY = "w1-warranty-refund-ledger-master-key-32b"


class _RedisStub:
    async def publish(self, _channel: str, _payload: str) -> None:
        return None


def _change_request_service(
    session: AsyncSession,
) -> TenantConfigChangeRequestService:
    tenant_configuration = TenantConfigurationService(
        runtime=TenantConfigurationRuntime(
            repository=PostgresTenantConfigurationRepository(session),
            credential_encryptor=TenantCredentialEncryptor(
                platform_master_key=_LEDGER_MASTER_KEY,
            ),
        ),
        session=session,
        redis_client=_RedisStub(),
    )
    return TenantConfigChangeRequestService(
        repository=PostgresTenantConfigChangeRequestRepository(session),
        tenant_configuration_service=tenant_configuration,
        event_appender=OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        ),
        session=session,
    )


@requires_postgres
@pytest.mark.asyncio
async def test_dual_control_propose_approve_apply_creates_resolvable_policy(
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"tenant-wr-ledger-{uuid.uuid4().hex}"
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _change_request_service(pg_session)

    proposed = await service.propose(
        tenant_id=tenant_id,
        change_type=TenantConfigChangeType.POLICY,
        payload={
            "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
            "parameters": _valid_parameters(),
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "effective_from": _NOW.isoformat(),
        },
        proposed_by="principal-a",
    )
    await service.approve(
        change_request_id=proposed.change_request_id,
        approved_by="principal-b",
        expected_tenant_id=tenant_id,
    )
    applied = await service.apply(
        change_request_id=proposed.change_request_id,
        expected_tenant_id=tenant_id,
        applied_by="principal-b",
    )
    assert applied.outcome_payload is not None
    assert applied.outcome_payload["kind"] == "governance_policy"

    policy = await resolve_warranty_refund_policy(
        repository=PostgresTenantConfigurationRepository(pg_session),
        tenant_id=tenant_id,
    )
    assert policy is not None
    assert policy.warranty_window_days == 730


@requires_postgres
@pytest.mark.asyncio
async def test_dual_control_propose_rejects_invalid_parameters(
    pg_session: AsyncSession,
) -> None:
    tenant_id = f"tenant-wr-ledger-{uuid.uuid4().hex}"
    await set_pg_rls_tenant(pg_session, tenant_id)
    service = _change_request_service(pg_session)
    bad_parameters = _valid_parameters()
    bad_parameters["warranty_window_days"] = -1

    with pytest.raises(TenantConfigChangeRequestLifecycleError):
        await service.propose(
            tenant_id=tenant_id,
            change_type=TenantConfigChangeType.POLICY,
            payload={
                "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
                "parameters": bad_parameters,
                "effective_from": _NOW.isoformat(),
            },
            proposed_by="principal-a",
        )
