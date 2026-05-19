"""Branch B — RBAC / capability governance regression tests.

Covers:

* ``AuthorityContext.capabilities`` + ``from_raw`` propagation.
* ``VerifiedIdentity.capabilities`` + translator.
* ``JWTProvider`` capabilities-claim extraction (array + scope-string
  shapes; malformed shapes raise ``AuthenticationError``).
* ``CapabilityGovernanceSubject`` value-object surface.
* ``SubjectKind.CAPABILITY`` enum value.
* ``RBACPolicy`` AUTHORITY-class doctrine (fail-closed on missing
  required capability, on absent held capability, and on a held set
  that lacks the requirement).
"""

from __future__ import annotations

import asyncio
from typing import Any

import jwt
import pytest

from app.auth import (
    AuthenticationError,
    Credential,
    VerifiedIdentity,
    verified_identity_to_authority,
)
from app.auth.providers import ClaimMapping, JWTProvider
from app.governance.context import GovernanceContext
from app.governance.enums import Decision, EnforcementStage
from app.governance.policies.builtin import RBACPolicy
from app.governance.subjects import (
    CapabilityGovernanceSubject,
    SubjectKind,
)
from app.identity import AuthorityContext, TenantId


# ─── AuthorityContext capabilities axis ────────────────────────────


def test_authority_context_default_capabilities_empty() -> None:
    auth = AuthorityContext(tenant_id=TenantId("acme"))
    assert auth.capabilities == frozenset()


def test_authority_context_carries_capabilities() -> None:
    auth = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=frozenset({"agents:invoke", "sessions:read"}),
    )
    assert "agents:invoke" in auth.capabilities
    assert "sessions:read" in auth.capabilities


def test_from_raw_propagates_capabilities() -> None:
    auth = AuthorityContext.from_raw(
        tenant_id="acme",
        capabilities=frozenset({"x", "y"}),
    )
    assert auth.capabilities == frozenset({"x", "y"})


def test_from_raw_defaults_empty_capabilities() -> None:
    auth = AuthorityContext.from_raw(tenant_id="acme")
    assert auth.capabilities == frozenset()


# ─── VerifiedIdentity + translator ─────────────────────────────────


def test_verified_identity_default_capabilities_empty() -> None:
    vi = VerifiedIdentity(tenant_id="acme")
    assert vi.capabilities == frozenset()


def test_translator_copies_capabilities() -> None:
    vi = VerifiedIdentity(
        tenant_id="acme",
        capabilities=frozenset({"agents:invoke"}),
    )
    auth = verified_identity_to_authority(vi)
    assert auth.capabilities == frozenset({"agents:invoke"})


# ─── JWTProvider capabilities claim ────────────────────────────────


HS_KEY = (
    "97c01989a35cac67133239a913d2813c"
    "a7ca2e9bb779a18ad25e63ce518624bb"
)

def _verify(provider: JWTProvider, token: str) -> VerifiedIdentity:
    return asyncio.run(
        provider.verify(Credential(scheme="Bearer", value=token))
    )


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, HS_KEY, algorithm="HS256")


def test_jwt_provider_default_claim_pinned() -> None:
    assert ClaimMapping().capabilities == "capabilities"


def test_jwt_provider_array_capabilities() -> None:
    token = _encode(
        {"sub": "alice", "capabilities": ["agents:invoke", "x"]}
    )
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    assert vi.capabilities == frozenset({"agents:invoke", "x"})


def test_jwt_provider_scope_string_capabilities() -> None:
    """OAuth2 ``scope`` shape: space-separated string."""
    token = _encode(
        {"sub": "alice", "capabilities": "agents:invoke sessions:read"}
    )
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    assert vi.capabilities == frozenset(
        {"agents:invoke", "sessions:read"}
    )


def test_jwt_provider_missing_capabilities_yields_empty() -> None:
    token = _encode({"sub": "alice"})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    assert vi.capabilities == frozenset()


def test_jwt_provider_custom_capabilities_claim() -> None:
    token = _encode({"sub": "alice", "perms": ["x", "y"]})
    mapping = ClaimMapping(capabilities="perms")
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        claim_mapping=mapping,
    )
    vi = _verify(provider, token)
    assert vi.capabilities == frozenset({"x", "y"})


def test_jwt_provider_disabled_capabilities_claim() -> None:
    """``capabilities=None`` in the mapping disables extraction
    entirely — the verified identity carries an empty set even when
    the token contains a capabilities claim."""
    token = _encode({"sub": "alice", "capabilities": ["x"]})
    mapping = ClaimMapping(capabilities=None)
    provider = JWTProvider(
        key=HS_KEY,
        algorithms=("HS256",),
        claim_mapping=mapping,
    )
    vi = _verify(provider, token)
    assert vi.capabilities == frozenset()


def test_jwt_provider_non_string_array_element_rejected() -> None:
    token = _encode({"sub": "alice", "capabilities": ["x", 42]})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


def test_jwt_provider_non_array_non_string_rejected() -> None:
    token = _encode({"sub": "alice", "capabilities": {"x": True}})
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    with pytest.raises(AuthenticationError):
        _verify(provider, token)


# ─── CapabilityGovernanceSubject ───────────────────────────────────


def test_capability_subject_kind_pinned() -> None:
    subject = CapabilityGovernanceSubject()
    assert subject.kind == SubjectKind.CAPABILITY


def test_capability_subject_to_dict_deterministic() -> None:
    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=frozenset({"x", "agents:invoke", "y"}),
        tenant_id="acme",
        actor="alice",
        metadata={"hint": "audit"},
    )
    d = subject.to_dict()
    assert d["kind"] == "capability"
    assert d["required_capability"] == "agents:invoke"
    assert d["held_capabilities"] == ["agents:invoke", "x", "y"]
    assert d["tenant_id"] == "acme"
    assert d["actor"] == "alice"
    assert d["metadata"] == {"hint": "audit"}


# ─── RBACPolicy doctrine ───────────────────────────────────────────


def _evaluate(
    subject: CapabilityGovernanceSubject,
    stage: EnforcementStage = EnforcementStage.PRE_EXECUTION,
):
    context = GovernanceContext(
        stage=stage,
        action="op.exec",
        resource="r1",
        subject=subject,
    )
    policy = RBACPolicy()
    return asyncio.run(policy.evaluate(context))


def test_rbac_grant_when_capability_held() -> None:
    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=frozenset({"agents:invoke"}),
    )
    results = _evaluate(subject)
    assert len(results) == 1
    assert results[0].decision == Decision.ALLOW
    assert results[0].rule_id == "capability_granted"


def test_rbac_deny_when_capability_missing_from_held() -> None:
    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=frozenset({"sessions:read"}),
    )
    results = _evaluate(subject)
    assert results[0].decision == Decision.DENY
    assert results[0].rule_id == "capability_missing"


def test_rbac_deny_when_held_set_empty() -> None:
    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=frozenset(),
    )
    results = _evaluate(subject)
    assert results[0].decision == Decision.DENY
    assert results[0].rule_id == "capability_missing"


def test_rbac_deny_when_required_unspecified() -> None:
    """AUTHORITY-class fail-closed on indeterminate config."""
    subject = CapabilityGovernanceSubject(
        required_capability="",
        held_capabilities=frozenset({"agents:invoke"}),
    )
    results = _evaluate(subject)
    assert results[0].decision == Decision.DENY
    assert results[0].rule_id == "capability_unspecified"
    assert results[0].metadata["fail_mode"] == "closed"
    assert results[0].metadata["policy_class"] == "authority"


def test_rbac_only_runs_at_pre_stages() -> None:
    """RBAC is a PRE-class policy — POST stages should not be in
    supported_stages."""
    assert (
        EnforcementStage.POST_EXECUTION
        not in RBACPolicy.supported_stages
    )
    assert (
        EnforcementStage.POST_RETRIEVAL
        not in RBACPolicy.supported_stages
    )


def test_rbac_applicable_kind_pinned() -> None:
    assert RBACPolicy.applicable_subject_kinds == frozenset(
        {SubjectKind.CAPABILITY}
    )


# ─── End-to-end: provider → AuthorityContext → subject → RBAC ──────


def test_end_to_end_jwt_to_rbac_allow() -> None:
    token = _encode(
        {
            "sub": "alice",
            "tenant_id": "acme",
            "capabilities": ["agents:invoke", "sessions:read"],
        }
    )
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    auth = verified_identity_to_authority(vi)

    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=auth.capabilities,
        tenant_id=auth.tenant_id,
        actor=auth.principal_id or "anonymous",
    )
    results = _evaluate(subject)
    assert results[0].decision == Decision.ALLOW


def test_end_to_end_jwt_to_rbac_deny() -> None:
    token = _encode(
        {
            "sub": "alice",
            "tenant_id": "acme",
            "capabilities": ["sessions:read"],
        }
    )
    provider = JWTProvider(key=HS_KEY, algorithms=("HS256",))
    vi = _verify(provider, token)
    auth = verified_identity_to_authority(vi)

    subject = CapabilityGovernanceSubject(
        required_capability="agents:invoke",
        held_capabilities=auth.capabilities,
        tenant_id=auth.tenant_id,
    )
    results = _evaluate(subject)
    assert results[0].decision == Decision.DENY
